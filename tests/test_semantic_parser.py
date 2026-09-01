import unittest

from telecom_text_to_sql.intent_parser import QueryIntent
from telecom_text_to_sql.intent_validator import validate_intent
from telecom_text_to_sql.semantic_parser import parse_explicit_intent
from telecom_text_to_sql.sql_generator import generate_sql_from_intent
from telecom_text_to_sql.sql_validator import validate_sql


class SemanticParserTests(unittest.TestCase):
    CASES = (
        (
            "How many customers are currently marked as Stayed?",
            ("COUNT(st.customer_id)", "st.customer_status = 'Stayed'"),
        ),
        (
            "Count the customers who are 65 years old or older.",
            ("COUNT(d.customer_id)", "d.age >= 65"),
        ),
        (
            "What is the average monthly charge for Month-to-Month customers?",
            ("AVG(s.monthly_charge)", "s.contract = 'Month-to-Month'"),
        ),
        (
            "Show the ten customers with the highest customer lifetime value.",
            ("st.cltv", "ORDER BY st.cltv DESC", "LIMIT 10"),
        ),
        (
            "Give me the customer count for every internet connection type.",
            ("s.internet_type", "COUNT(s.customer_id)", "GROUP BY s.internet_type"),
        ),
        (
            "Which payment method has the lowest average total revenue?",
            ("s.payment_method", "AVG(s.total_revenue)", "ORDER BY AVG(s.total_revenue) ASC", "LIMIT 1"),
        ),
        (
            "What is the average monthly data download for internet customers?",
            ("AVG(s.avg_monthly_gb_download)", "s.internet_service = 'Yes'"),
        ),
        (
            "How many churned customers live in each city?",
            ("l.city", "COUNT(CASE WHEN st.churn_value = 1", "GROUP BY l.city"),
        ),
        (
            "List fifteen customers whose satisfaction score is 2 or lower.",
            ("st.satisfaction_score <= 2", "LIMIT 15"),
        ),
        (
            "What percentage of all customers have churned?",
            ("CASE WHEN st.churn_value = 1", "AS percentage_of_customers"),
        ),
        (
            "Which contract type has the largest number of churned customers?",
            ("s.contract", "COUNT(CASE WHEN st.churn_value = 1", "GROUP BY s.contract", "DESC", "LIMIT 1"),
        ),
        (
            "Which ZIP code has the largest population?",
            ("p.zip_code", "p.population", "ORDER BY p.population DESC", "LIMIT 1"),
        ),
        (
            "Show the average customer tenure for each customer status.",
            ("st.customer_status", "AVG(s.tenure_in_months)", "GROUP BY st.customer_status"),
        ),
        (
            "Find the five customers with the highest average monthly GB download.",
            ("s.avg_monthly_gb_download", "ORDER BY s.avg_monthly_gb_download DESC", "LIMIT 5"),
        ),
        (
            "How many customers are married and have dependents?",
            ("COUNT(d.customer_id)", "d.married = 'Yes'", "d.dependents = 'Yes'"),
        ),
    )

    def test_representative_supported_scenarios_compile_safely(self):
        for question, expected_fragments in self.CASES:
            with self.subTest(question=question):
                raw_intent = parse_explicit_intent(question)
                self.assertIsNotNone(raw_intent)
                intent = QueryIntent.model_validate(raw_intent)
                validation = validate_intent(intent)
                self.assertTrue(
                    validation.is_complete,
                    msg=validation.reasons,
                )
                sql = generate_sql_from_intent(intent)
                self.assertTrue(validate_sql(sql).is_valid)
                for fragment in expected_fragments:
                    self.assertIn(fragment, sql)

    def test_grouping_quantifier_paraphrases(self):
        questions = (
            "Give customer count for each internet type.",
            "Give customer count for every internet type.",
            "Give customer count per internet type.",
            "Give customer count by internet type.",
            "Give the internet-type-wise customer count.",
        )

        for question in questions:
            with self.subTest(question=question):
                intent = QueryIntent.model_validate(
                    parse_explicit_intent(question)
                )
                self.assertEqual(
                    intent.group_by,
                    ["services.internet_type"],
                )

    def test_comparison_words_do_not_become_ranking_words(self):
        intent = QueryIntent.model_validate(
            parse_explicit_intent(
                "Find customers with at least 48 months of tenure."
            )
        )
        sql = generate_sql_from_intent(intent)

        self.assertIn("s.tenure_in_months >= 48", sql)
        self.assertNotIn("ORDER BY", sql)
        self.assertNotIn("LIMIT", sql)

    def test_tenure_years_are_converted_to_schema_months(self):
        intent = QueryIntent.model_validate(
            parse_explicit_intent(
                "People staying with us 2 years or more."
            )
        )
        sql = generate_sql_from_intent(intent)

        self.assertIn("s.tenure_in_months >= 24", sql)
        self.assertNotIn("ORDER BY", sql)
        self.assertNotIn("LIMIT", sql)


if __name__ == "__main__":
    unittest.main()
