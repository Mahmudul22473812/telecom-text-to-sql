import unittest

from telecom_text_to_sql.intent_normalizer import normalize_intent
from telecom_text_to_sql.intent_parser import QueryIntent
from telecom_text_to_sql.intent_validator import validate_intent


class ClarificationSemanticsTests(unittest.TestCase):
    CASES = (
        (
            "Show loyal customers.",
            ("tenure", "loyal"),
            ("threshold for threshold",),
        ),
        (
            "Which contract is performing best?",
            ("metric", "contract"),
            (),
        ),
        (
            "Find customers with a high churn score.",
            ("churn score", "high"),
            (),
        ),
        (
            "Which city has healthy customer retention?",
            ("metric", "city", "retention"),
            ("cltv",),
        ),
        (
            "Show customers with affordable monthly charges.",
            ("monthly charge", "affordable"),
            (),
        ),
        (
            "Which payment method is the most effective?",
            ("metric", "payment method"),
            (),
        ),
        (
            "Find young customers who spend a lot.",
            ("age", "young"),
            ("ranking",),
        ),
        (
            "Show customers with poor service experience.",
            ("poor service experience", "satisfaction"),
            ("ranking",),
        ),
    )

    def test_follow_ups_are_contextual_and_non_leading(self):
        for question, required_terms, forbidden_terms in self.CASES:
            with self.subTest(question=question):
                intent = normalize_intent(question, QueryIntent())
                validation = validate_intent(intent)

                self.assertFalse(validation.is_complete)
                follow_up = validation.clarification_question.lower()
                for term in required_terms:
                    self.assertIn(term, follow_up)
                for term in forbidden_terms:
                    self.assertNotIn(term, follow_up)

    def test_young_spenders_preserve_two_independent_ambiguities(self):
        intent = normalize_intent(
            "Find young customers who spend a lot.",
            QueryIntent(),
        )
        validation = validate_intent(intent)

        self.assertIn("young_age_threshold", validation.unresolved_slots)
        self.assertIn("spending_metric", validation.unresolved_slots)


if __name__ == "__main__":
    unittest.main()
