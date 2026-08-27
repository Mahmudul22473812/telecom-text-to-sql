import unittest

from intent_parser import QueryIntent
from pipeline import run_pipeline


class PipelineTests(unittest.TestCase):
    def test_returns_needs_clarification_without_blocking(self):
        intent = QueryIntent(
            target_entity="customers",
            unresolved_slots=["ranking_metric"],
        )

        def ambiguity_checker(_question):
            return {
                "ambiguous": True,
                "clarification_question": "Which metric?",
                "unresolved_slots": ["ranking_metric"],
                "reasons": ["Metric is missing."],
                "intent": intent,
            }

        result = run_pipeline(
            "Who are the best customers?",
            execute=False,
            ambiguity_checker=ambiguity_checker,
        )

        self.assertEqual(result.status, "needs_clarification")
        self.assertTrue(result.initially_ambiguous)
        self.assertEqual(
            result.clarification_questions,
            ["Which metric?"],
        )

    def test_runs_clear_question_without_database(self):
        intent = QueryIntent(
            target_entity="customers",
            metric="demographics.customer_id",
            aggregation="COUNT",
        )

        def ambiguity_checker(_question):
            return {
                "ambiguous": False,
                "clarification_question": None,
                "unresolved_slots": [],
                "reasons": [],
                "intent": intent,
            }

        result = run_pipeline(
            "Count customers",
            execute=False,
            ambiguity_checker=ambiguity_checker,
        )

        self.assertEqual(result.status, "success")
        self.assertFalse(result.initially_ambiguous)
        self.assertIn("COUNT(d.customer_id)", result.sql)
        self.assertGreaterEqual(result.total_latency_ms, 0)

    def test_executor_is_injected_for_deployment_testing(self):
        intent = QueryIntent(
            target_entity="customers",
            metric="demographics.customer_id",
            aggregation="COUNT",
        )

        def ambiguity_checker(_question):
            return {
                "ambiguous": False,
                "clarification_question": None,
                "unresolved_slots": [],
                "reasons": [],
                "intent": intent,
            }

        def query_executor(_sql):
            return ["count_customer_id"], [(7043,)]

        result = run_pipeline(
            "Count customers",
            execute=True,
            ambiguity_checker=ambiguity_checker,
            query_executor=query_executor,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.columns, ["count_customer_id"])
        self.assertEqual(result.rows, [(7043,)])

    def test_errors_are_structured(self):
        def ambiguity_checker(_question):
            raise RuntimeError("model unavailable")

        result = run_pipeline(
            "Count customers",
            execute=False,
            ambiguity_checker=ambiguity_checker,
        )

        self.assertEqual(result.status, "error")
        self.assertIn("model unavailable", result.error)


if __name__ == "__main__":
    unittest.main()
