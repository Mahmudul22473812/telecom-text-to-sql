from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from .clarification import check_ambiguity
from .intent_parser import QueryIntent
from .intent_resolver import resolve_intent
from .intent_validator import validate_intent
from .query_executor import execute_query
from .request_guard import unsupported_reason
from .sql_generator import generate_sql_from_intent
from .sql_validator import validate_sql


@dataclass
class PipelineResult:
    """Structured output from one Text-to-SQL request."""

    question: str
    status: str
    initially_ambiguous: bool = False
    intent: QueryIntent | None = None
    clarification_questions: list[str] = field(default_factory=list)
    clarification_answers: list[str] = field(default_factory=list)
    sql: str | None = None
    sql_validation_errors: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    error: str | None = None

    @property
    def total_latency_ms(self) -> float:
        return self.timings_ms.get("total", 0.0)

    def to_dict(self, *, include_rows: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "question": self.question,
            "status": self.status,
            "initially_ambiguous": self.initially_ambiguous,
            "intent": (
                self.intent.model_dump(mode="json")
                if self.intent
                else None
            ),
            "clarification_questions": self.clarification_questions,
            "clarification_answers": self.clarification_answers,
            "sql": self.sql,
            "sql_validation_errors": self.sql_validation_errors,
            "columns": self.columns,
            "timings_ms": self.timings_ms,
            "error": self.error,
        }

        if include_rows:
            data["rows"] = [
                list(row)
                for row in self.rows
            ]

        return data


ClarificationProvider = Callable[[str, QueryIntent], str | None]


def run_pipeline(
    question: str,
    *,
    clarification_answers: Iterable[str] | None = None,
    clarification_provider: ClarificationProvider | None = None,
    execute: bool = True,
    max_clarifications: int = 5,
    ambiguity_checker: Callable = check_ambiguity,
    intent_resolver: Callable = resolve_intent,
    sql_generator: Callable = generate_sql_from_intent,
    query_executor: Callable = execute_query,
) -> PipelineResult:
    """
    Run the complete clarification-aware Text-to-SQL pipeline.

    Without answers or a provider, an ambiguous request returns
    ``needs_clarification`` instead of blocking for terminal input.
    This makes the same function suitable for a CLI, API, and evaluator.
    """

    started_at = perf_counter()
    result = PipelineResult(
        question=question,
        status="error",
    )

    def finish() -> PipelineResult:
        result.timings_ms["total"] = round(
            (perf_counter() - started_at) * 1000,
            3,
        )
        return result

    if not isinstance(question, str) or not question.strip():
        result.error = "Question must be a non-empty string."
        return finish()

    scope_error = unsupported_reason(question)

    if scope_error:
        result.status = "unsupported"
        result.error = scope_error
        return finish()

    answers = iter(clarification_answers or [])

    try:
        stage_started = perf_counter()
        ambiguity = ambiguity_checker(question.strip())
        result.timings_ms["intent_analysis"] = round(
            (perf_counter() - stage_started) * 1000,
            3,
        )
        result.initially_ambiguous = bool(ambiguity["ambiguous"])
        current_intent = ambiguity["intent"]
        result.intent = current_intent

        clarification_count = 0

        while ambiguity["ambiguous"]:
            clarification_count += 1

            if clarification_count > max_clarifications:
                result.error = (
                    "Maximum clarification turns exceeded before the "
                    "intent became complete."
                )
                return finish()

            clarification_question = ambiguity[
                "clarification_question"
            ]

            if not clarification_question:
                result.error = (
                    "Intent is incomplete but no clarification question "
                    "was produced."
                )
                return finish()

            result.clarification_questions.append(
                clarification_question
            )

            try:
                answer = next(answers)
            except StopIteration:
                answer = (
                    clarification_provider(
                        clarification_question,
                        current_intent,
                    )
                    if clarification_provider
                    else None
                )

            if answer is None:
                result.status = "needs_clarification"
                result.intent = current_intent
                return finish()

            if not isinstance(answer, str) or not answer.strip():
                result.error = "Clarification answers must be non-empty."
                return finish()

            result.clarification_answers.append(answer.strip())
            stage_started = perf_counter()
            current_intent = intent_resolver(
                original_question=question,
                intent=current_intent,
                clarification_answer=answer,
            )
            result.timings_ms["intent_resolution"] = round(
                result.timings_ms.get("intent_resolution", 0.0)
                + (perf_counter() - stage_started) * 1000,
                3,
            )
            result.intent = current_intent

            validation = validate_intent(current_intent)
            ambiguity = {
                "ambiguous": not validation.is_complete,
                "clarification_question": (
                    validation.clarification_question
                ),
                "unresolved_slots": validation.unresolved_slots,
                "reasons": validation.reasons,
                "intent": current_intent,
            }

        stage_started = perf_counter()
        sql = sql_generator(current_intent)
        result.timings_ms["sql_generation"] = round(
            (perf_counter() - stage_started) * 1000,
            3,
        )
        result.sql = sql

        sql_validation = validate_sql(sql)

        if not sql_validation.is_valid:
            result.status = "sql_rejected"
            result.sql_validation_errors = sql_validation.errors
            return finish()

        if execute:
            stage_started = perf_counter()
            columns, rows = query_executor(sql)
            result.timings_ms["execution"] = round(
                (perf_counter() - stage_started) * 1000,
                3,
            )
            result.columns = list(columns)
            result.rows = list(rows)

        result.status = "success"
        return finish()

    except Exception as error:
        result.error = f"{type(error).__name__}: {error}"
        return finish()
