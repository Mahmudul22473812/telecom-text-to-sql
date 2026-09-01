import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from telecom_text_to_sql.pipeline import PipelineResult, run_pipeline
from telecom_text_to_sql.query_executor import execute_query
from telecom_text_to_sql.sql_validator import validate_sql


DEFAULT_CASES_FILE = Path(__file__).parent / "comprehensive_cases.json"
DEFAULT_REPORT_FILE = Path(__file__).parent / "reports" / "latest.json"

RELEASE_GATES = {
    "minimum_cases": 30,
    "minimum_runs": 3,
    "clarification_f1": 0.90,
    "case_pass_rate": 0.90,
    "execution_accuracy": 0.90,
    "sql_valid_rate": 1.00,
    "unsafe_rejection_rate": 1.00,
    "safe_acceptance_rate": 1.00,
    "maximum_runtime_failure_rate": 0.00,
    "stability_rate": 0.95,
}

SAFE_SQL_CASES = [
    "SELECT customer_id FROM services LIMIT 5;",
    "SELECT AVG(monthly_charge) FROM services;",
    "SELECT 'DROP TABLE status;' AS harmless_text;",
]

UNSAFE_SQL_CASES = [
    "DROP TABLE services;",
    "SELECT * FROM services; DELETE FROM services;",
    "SELECT pg_read_file('/etc/passwd');",
    "SELECT * INTO services_copy FROM services;",
    "SELECT * FROM services FOR UPDATE;",
    "UPDATE services SET monthly_charge = 0;",
]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(
        value,
        bool,
    )


def values_equal(
    actual: Any,
    expected: Any,
    *,
    tolerance: float = 1e-6,
) -> bool:
    if _is_number(actual) and _is_number(expected):
        return math.isclose(
            float(actual),
            float(expected),
            rel_tol=tolerance,
            abs_tol=tolerance,
        )

    return actual == expected


def rows_equal(
    actual_rows: list[tuple],
    expected_rows: list[tuple],
    *,
    order_sensitive: bool = True,
    tolerance: float = 1e-6,
) -> bool:
    if len(actual_rows) != len(expected_rows):
        return False

    actual = list(actual_rows)
    expected = list(expected_rows)

    if not order_sensitive:
        sort_key = lambda row: tuple(str(value) for value in row)
        actual.sort(key=sort_key)
        expected.sort(key=sort_key)

    for actual_row, expected_row in zip(actual, expected):
        if len(actual_row) != len(expected_row):
            return False

        if not all(
            values_equal(
                actual_value,
                expected_value,
                tolerance=tolerance,
            )
            for actual_value, expected_value
            in zip(actual_row, expected_row)
        ):
            return False

    return True


def percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = max(
        0,
        math.ceil(percentage * len(ordered)) - 1,
    )
    return ordered[index]


def _stable_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.normalize())

    if isinstance(value, float):
        return round(value, 8)

    if isinstance(value, tuple):
        return [_stable_value(item) for item in value]

    if isinstance(value, list):
        return [_stable_value(item) for item in value]

    if isinstance(value, dict):
        return {
            key: _stable_value(item)
            for key, item in sorted(value.items())
        }

    return value


def result_signature(result: PipelineResult) -> str:
    intent = (
        result.intent.model_dump(mode="json")
        if result.intent
        else None
    )
    normalized_sql = (
        " ".join(result.sql.split())
        if result.sql
        else None
    )
    signature = {
        "initially_ambiguous": result.initially_ambiguous,
        "status": result.status,
        "intent": intent,
        "sql": normalized_sql,
        "rows": _stable_value(result.rows),
        "error": result.error,
    }
    return json.dumps(signature, sort_keys=True, default=str)


def evaluate_sql_safety() -> dict[str, Any]:
    safe_results = [
        validate_sql(sql).is_valid
        for sql in SAFE_SQL_CASES
    ]
    unsafe_results = [
        not validate_sql(sql).is_valid
        for sql in UNSAFE_SQL_CASES
    ]

    return {
        "safe_cases": len(safe_results),
        "safe_accepted": sum(safe_results),
        "safe_acceptance_rate": (
            sum(safe_results) / len(safe_results)
        ),
        "unsafe_cases": len(unsafe_results),
        "unsafe_rejected": sum(unsafe_results),
        "unsafe_rejection_rate": (
            sum(unsafe_results) / len(unsafe_results)
        ),
    }


def evaluate_case(
    case: dict[str, Any],
    *,
    execute: bool,
    reference_cache: dict[str, tuple[list[str], list[tuple]]],
) -> tuple[dict[str, Any], str]:
    answers = case.get("clarification_answers", [])
    result = run_pipeline(
        case["question"],
        clarification_answers=answers,
        execute=execute,
    )

    expected_ambiguous = bool(case["expected_ambiguous"])
    classification_correct = (
        result.initially_ambiguous == expected_ambiguous
    )
    expected_status = case.get("expected_status") or (
        "needs_clarification"
        if expected_ambiguous and not answers
        else "success"
    )
    status_correct = result.status == expected_status
    expected_clarification_terms = [
        str(term).lower()
        for term in case.get("expected_clarification_contains", [])
    ]
    clarification_text = " ".join(
        result.clarification_questions
    ).lower()
    clarification_content_correct = all(
        term in clarification_text
        for term in expected_clarification_terms
    )

    sql_valid = (
        validate_sql(result.sql).is_valid
        if result.sql
        else None
    )
    execution_match = None
    reference_error = None
    reference_sql = case.get("reference_sql")

    if reference_sql and execute and result.status == "success":
        try:
            if reference_sql not in reference_cache:
                reference_cache[reference_sql] = execute_query(
                    reference_sql
                )

            _, reference_rows = reference_cache[reference_sql]
            execution_match = rows_equal(
                result.rows,
                reference_rows,
                order_sensitive=case.get("order_sensitive", True),
            )
        except Exception as error:
            reference_error = f"{type(error).__name__}: {error}"
            execution_match = False

    passed = (
        classification_correct
        and status_correct
        and clarification_content_correct
    )

    if result.sql is not None:
        passed = passed and sql_valid is True

    if reference_sql and execute:
        passed = passed and execution_match is True

    case_result = {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expected_ambiguous": expected_ambiguous,
        "predicted_ambiguous": result.initially_ambiguous,
        "classification_correct": classification_correct,
        "expected_status": expected_status,
        "actual_status": result.status,
        "status_correct": status_correct,
        "expected_clarification_contains": expected_clarification_terms,
        "clarification_content_correct": clarification_content_correct,
        "clarification_questions": result.clarification_questions,
        "clarification_answers": result.clarification_answers,
        "intent": (
            result.intent.model_dump(mode="json")
            if result.intent
            else None
        ),
        "sql": result.sql,
        "sql_valid": sql_valid,
        "sql_validation_errors": result.sql_validation_errors,
        "columns": result.columns,
        "execution_match": execution_match,
        "generated_row_count": len(result.rows),
        "reference_error": reference_error,
        "pipeline_error": result.error,
        "timings_ms": result.timings_ms,
        "passed": passed,
    }
    return case_result, result_signature(result)


def calculate_metrics(
    cases: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    signatures: dict[str, list[str]],
    *,
    runs: int,
    execute: bool,
    safety: dict[str, Any],
) -> dict[str, Any]:
    true_positive = sum(
        item["expected_ambiguous"]
        and item["predicted_ambiguous"]
        for item in evaluations
    )
    false_positive = sum(
        not item["expected_ambiguous"]
        and item["predicted_ambiguous"]
        for item in evaluations
    )
    false_negative = sum(
        item["expected_ambiguous"]
        and not item["predicted_ambiguous"]
        for item in evaluations
    )
    true_negative = sum(
        not item["expected_ambiguous"]
        and not item["predicted_ambiguous"]
        for item in evaluations
    )

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = (
        true_positive / precision_denominator
        if precision_denominator
        else 0.0
    )
    recall = (
        true_positive / recall_denominator
        if recall_denominator
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    execution_checks = [
        item
        for item in evaluations
        if item["execution_match"] is not None
    ]
    sql_checks = [
        item
        for item in evaluations
        if item["sql_valid"] is not None
    ]
    runtime_failures = [
        item
        for item in evaluations
        if item["actual_status"] == "error"
    ]
    latencies = [
        item["timings_ms"].get("total", 0.0)
        for item in evaluations
    ]
    stable_cases = sum(
        len(set(case_signatures)) == 1
        for case_signatures in signatures.values()
    )

    category_totals: dict[str, int] = defaultdict(int)
    category_passes: dict[str, int] = defaultdict(int)

    for item in evaluations:
        category_totals[item["category"]] += 1
        category_passes[item["category"]] += int(item["passed"])

    category_metrics = {
        category: {
            "evaluations": total,
            "passed": category_passes[category],
            "pass_rate": category_passes[category] / total,
        }
        for category, total in sorted(category_totals.items())
    }

    total_evaluations = len(evaluations)
    classification_accuracy = (
        (true_positive + true_negative) / total_evaluations
        if total_evaluations
        else 0.0
    )
    execution_accuracy = (
        sum(item["execution_match"] is True for item in execution_checks)
        / len(execution_checks)
        if execution_checks
        else 0.0
    )
    sql_valid_rate = (
        sum(item["sql_valid"] is True for item in sql_checks)
        / len(sql_checks)
        if sql_checks
        else 0.0
    )
    case_pass_rate = (
        sum(item["passed"] for item in evaluations)
        / total_evaluations
        if total_evaluations
        else 0.0
    )
    runtime_failure_rate = (
        len(runtime_failures) / total_evaluations
        if total_evaluations
        else 0.0
    )
    stability_rate = (
        stable_cases / len(cases)
        if cases
        else 0.0
    )

    metrics = {
        "cases": len(cases),
        "runs": runs,
        "evaluations": total_evaluations,
        "classification_accuracy": classification_accuracy,
        "clarification_precision": precision,
        "clarification_recall": recall,
        "clarification_f1": f1,
        "confusion_matrix": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
        },
        "case_pass_rate": case_pass_rate,
        "execution_checks": len(execution_checks),
        "execution_accuracy": execution_accuracy,
        "sql_checks": len(sql_checks),
        "sql_valid_rate": sql_valid_rate,
        "runtime_failures": len(runtime_failures),
        "runtime_failure_rate": runtime_failure_rate,
        "stable_cases": stable_cases,
        "stability_rate": stability_rate,
        "mean_latency_ms": (
            statistics.fmean(latencies)
            if latencies
            else 0.0
        ),
        "p95_latency_ms": percentile(latencies, 0.95),
        "categories": category_metrics,
        "safety": safety,
        "database_execution_enabled": execute,
    }

    gate_results = {
        "minimum_cases": len(cases) >= RELEASE_GATES["minimum_cases"],
        "minimum_runs": runs >= RELEASE_GATES["minimum_runs"],
        "clarification_f1": f1 >= RELEASE_GATES["clarification_f1"],
        "case_pass_rate": (
            case_pass_rate >= RELEASE_GATES["case_pass_rate"]
        ),
        "execution_accuracy": (
            execute
            and execution_accuracy
            >= RELEASE_GATES["execution_accuracy"]
        ),
        "sql_valid_rate": (
            sql_valid_rate >= RELEASE_GATES["sql_valid_rate"]
        ),
        "unsafe_rejection_rate": (
            safety["unsafe_rejection_rate"]
            >= RELEASE_GATES["unsafe_rejection_rate"]
        ),
        "safe_acceptance_rate": (
            safety["safe_acceptance_rate"]
            >= RELEASE_GATES["safe_acceptance_rate"]
        ),
        "runtime_failure_rate": (
            runtime_failure_rate
            <= RELEASE_GATES["maximum_runtime_failure_rate"]
        ),
        "stability_rate": (
            runs >= RELEASE_GATES["minimum_runs"]
            and stability_rate >= RELEASE_GATES["stability_rate"]
        ),
    }
    metrics["release_gates"] = gate_results
    metrics["release_ready"] = all(gate_results.values())
    return metrics


def run_evaluation(
    cases: list[dict[str, Any]],
    *,
    runs: int,
    execute: bool,
) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    signatures: dict[str, list[str]] = defaultdict(list)
    reference_cache: dict[str, tuple[list[str], list[tuple]]] = {}

    for run_number in range(1, runs + 1):
        print(f"\nRun {run_number}/{runs}", flush=True)

        for index, case in enumerate(cases, start=1):
            case_result, signature = evaluate_case(
                case,
                execute=execute,
                reference_cache=reference_cache,
            )
            case_result["run"] = run_number
            evaluations.append(case_result)
            signatures[case["id"]].append(signature)
            outcome = "PASS" if case_result["passed"] else "FAIL"
            print(
                f"[{index:02d}/{len(cases):02d}] "
                f"{outcome} {case['id']} "
                f"({case_result['timings_ms'].get('total', 0):.0f} ms)",
                flush=True,
            )

    safety = evaluate_sql_safety()
    metrics = calculate_metrics(
        cases,
        evaluations,
        signatures,
        runs=runs,
        execute=execute,
        safety=safety,
    )
    return {
        "release_gates": RELEASE_GATES,
        "metrics": metrics,
        "evaluations": evaluations,
    }


def print_summary(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    print("\n" + "=" * 72)
    print("END-TO-END DEPLOYMENT EVALUATION")
    print("=" * 72)
    print(f"Cases: {metrics['cases']}")
    print(f"Runs: {metrics['runs']}")
    print(
        "Classification accuracy: "
        f"{metrics['classification_accuracy']:.2%}"
    )
    print(
        "Clarification precision/recall/F1: "
        f"{metrics['clarification_precision']:.2%} / "
        f"{metrics['clarification_recall']:.2%} / "
        f"{metrics['clarification_f1']:.2%}"
    )
    print(f"Case pass rate: {metrics['case_pass_rate']:.2%}")
    print(
        "Execution accuracy: "
        f"{metrics['execution_accuracy']:.2%} "
        f"({metrics['execution_checks']} checks)"
    )
    print(f"SQL valid rate: {metrics['sql_valid_rate']:.2%}")
    print(f"Runtime failures: {metrics['runtime_failures']}")
    print(f"Stability: {metrics['stability_rate']:.2%}")
    print(f"Mean latency: {metrics['mean_latency_ms']:.0f} ms")
    print(f"P95 latency: {metrics['p95_latency_ms']:.0f} ms")
    print(
        "Safety rejection/acceptance: "
        f"{metrics['safety']['unsafe_rejection_rate']:.2%} / "
        f"{metrics['safety']['safe_acceptance_rate']:.2%}"
    )

    failed = [
        item
        for item in report["evaluations"]
        if not item["passed"]
    ]

    if failed:
        print("\nFailed evaluations:")

        for item in failed:
            reason = (
                item["pipeline_error"]
                or item["reference_error"]
                or (
                    f"expected {item['expected_status']}, "
                    f"got {item['actual_status']}; "
                    f"execution_match={item['execution_match']}"
                )
            )
            print(
                f"- run {item['run']} {item['id']}: {reason}"
            )

    print("\nRelease gates:")

    for gate, passed in metrics["release_gates"].items():
        print(f"- {'PASS' if passed else 'FAIL'} {gate}")

    print(
        "\nRelease decision: "
        + ("READY" if metrics["release_ready"] else "NOT READY")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate clarification, SQL execution accuracy, safety, "
            "latency, and stability."
        )
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_FILE,
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Skip PostgreSQL and result-equivalence checks.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_FILE,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.runs < 1:
        print("--runs must be at least 1.", file=sys.stderr)
        return 2

    with args.cases.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    report = run_evaluation(
        cases,
        runs=args.runs,
        execute=not args.no_execute,
    )
    print_summary(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            indent=2,
            default=str,
        )

    print(f"\nReport written to: {args.output.resolve()}")
    return 0 if report["metrics"]["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
