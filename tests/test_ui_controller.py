import unittest

from telecom_text_to_sql.pipeline import PipelineResult
from telecom_text_to_sql.ui_controller import (
    ConversationState,
    process_message,
)


class UIControllerTests(unittest.TestCase):
    def test_clear_question_completes_and_resets_pending_state(self):
        calls = []

        def runner(question, **kwargs):
            calls.append((question, kwargs))
            return PipelineResult(
                question=question,
                status="success",
                columns=["count_customer_id"],
                rows=[(7043,)],
            )

        state = ConversationState()
        result = process_message(
            state,
            "Count all customers",
            pipeline_runner=runner,
        )

        self.assertEqual(result.status, "success")
        self.assertFalse(state.awaiting_clarification)
        self.assertEqual(len(state.messages), 2)
        self.assertEqual(calls[0][0], "Count all customers")
        self.assertTrue(calls[0][1]["execute"])

    def test_clarification_answers_are_preserved_across_turns(self):
        calls = []

        def runner(question, **kwargs):
            answers = list(kwargs["clarification_answers"])
            calls.append((question, answers))
            if not answers:
                return PipelineResult(
                    question=question,
                    status="needs_clarification",
                    clarification_questions=[
                        "What tenure defines a loyal customer?"
                    ],
                )
            return PipelineResult(
                question=question,
                status="success",
                sql="SELECT customer_id FROM services;",
            )

        state = ConversationState()
        first_result = process_message(
            state,
            "Show loyal customers",
            pipeline_runner=runner,
        )
        second_result = process_message(
            state,
            "At least 48 months",
            pipeline_runner=runner,
        )

        self.assertEqual(first_result.status, "needs_clarification")
        self.assertEqual(second_result.status, "success")
        self.assertEqual(calls[1], ("Show loyal customers", ["At least 48 months"]))
        self.assertFalse(state.awaiting_clarification)
        self.assertEqual(
            [message["kind"] for message in state.messages],
            ["question", "clarification", "clarification_answer", "result"],
        )

    def test_unsupported_result_is_renderable_and_ends_turn(self):
        def runner(question, **_kwargs):
            return PipelineResult(
                question=question,
                status="unsupported",
                error="Only read-only analysis is supported.",
            )

        state = ConversationState()
        result = process_message(
            state,
            "Delete every customer",
            pipeline_runner=runner,
        )

        self.assertEqual(result.status, "unsupported")
        self.assertFalse(state.awaiting_clarification)
        self.assertEqual(state.messages[-1]["result"], result)

    def test_empty_message_is_rejected(self):
        with self.assertRaises(ValueError):
            process_message(
                ConversationState(),
                "   ",
                pipeline_runner=lambda *_args, **_kwargs: None,
            )


if __name__ == "__main__":
    unittest.main()
