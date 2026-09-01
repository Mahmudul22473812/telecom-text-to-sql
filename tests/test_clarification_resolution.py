import unittest
from unittest.mock import patch

from telecom_text_to_sql.intent_normalizer import normalize_intent
from telecom_text_to_sql.intent_parser import QueryIntent
from telecom_text_to_sql.intent_resolver import resolve_intent
from telecom_text_to_sql.intent_validator import validate_intent
from telecom_text_to_sql.sql_generator import generate_sql_from_intent


class ClarificationResolutionTests(unittest.TestCase):
    @patch(
        "telecom_text_to_sql.intent_resolver.retrieve_relevant_columns",
        return_value=[],
    )
    def test_grouped_ranking_answer_preserves_aggregation(
        self,
        _retrieve,
    ):
        intent = normalize_intent(
            "Which contract is performing best?",
            QueryIntent(),
        )
        resolved = resolve_intent(
            "Which contract is performing best?",
            intent,
            "highest average total revenue",
        )

        self.assertTrue(validate_intent(resolved).is_complete)
        sql = generate_sql_from_intent(resolved)
        self.assertIn("AVG(s.total_revenue)", sql)
        self.assertIn("GROUP BY s.contract", sql)
        self.assertIn("ORDER BY AVG(s.total_revenue) DESC", sql)

    @patch(
        "telecom_text_to_sql.intent_resolver.retrieve_relevant_columns",
        return_value=[],
    )
    def test_city_retention_answer_uses_churned_customer_count(
        self,
        _retrieve,
    ):
        intent = normalize_intent(
            "Which city has healthy customer retention?",
            QueryIntent(),
        )
        resolved = resolve_intent(
            "Which city has healthy customer retention?",
            intent,
            "fewest churned customers",
        )

        self.assertTrue(validate_intent(resolved).is_complete)
        sql = generate_sql_from_intent(resolved)
        self.assertIn("LEFT JOIN status st", sql)
        self.assertIn("CASE WHEN st.churn_value = 1", sql)
        self.assertNotIn("WHERE st.churn_value = 1", sql)
        self.assertIn("GROUP BY l.city", sql)
        self.assertIn("ORDER BY COUNT(CASE WHEN", sql)

    @patch(
        "telecom_text_to_sql.intent_resolver.retrieve_relevant_columns",
        return_value=[],
    )
    def test_young_spender_resolves_two_questions_in_sequence(
        self,
        _retrieve,
    ):
        question = "Find young customers who spend a lot."
        intent = normalize_intent(question, QueryIntent())
        age_resolved = resolve_intent(question, intent, "30 or younger")
        age_validation = validate_intent(age_resolved)

        self.assertFalse(age_validation.is_complete)
        self.assertIn("spending", age_validation.clarification_question)

        spending_resolved = resolve_intent(
            question,
            age_resolved,
            "total charges above 1000",
        )
        self.assertTrue(validate_intent(spending_resolved).is_complete)
        sql = generate_sql_from_intent(spending_resolved)
        self.assertIn("d.age <= 30", sql)
        self.assertIn("s.total_charges > 1000", sql)

    @patch(
        "telecom_text_to_sql.intent_resolver.retrieve_relevant_columns",
        return_value=[],
    )
    def test_service_experience_answer_resolves_metric_and_threshold(
        self,
        _retrieve,
    ):
        question = "Show customers with poor service experience."
        intent = normalize_intent(question, QueryIntent())
        resolved = resolve_intent(
            question,
            intent,
            "satisfaction score 2 or lower",
        )

        self.assertTrue(validate_intent(resolved).is_complete)
        sql = generate_sql_from_intent(resolved)
        self.assertIn("st.satisfaction_score <= 2", sql)


if __name__ == "__main__":
    unittest.main()
