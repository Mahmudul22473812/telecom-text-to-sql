import unittest

from telecom_text_to_sql.intent_parser import FilterCondition, QueryIntent
from telecom_text_to_sql.sql_generator import generate_sql_from_intent
from telecom_text_to_sql.sql_validator import validate_sql


class SQLGeneratorTests(unittest.TestCase):
    def test_generates_grouped_customer_count_ranking(self):
        intent = QueryIntent(
            target_entity="payment methods",
            selected_fields=["services.payment_method"],
            metric="services.customer_id",
            aggregation="COUNT",
            group_by=["services.payment_method"],
            order_by="services.customer_id",
            order_direction="DESC",
            limit=1,
        )

        sql = generate_sql_from_intent(intent)

        self.assertIn("SELECT s.payment_method", sql)
        self.assertIn("COUNT(s.customer_id)", sql)
        self.assertIn("GROUP BY s.payment_method", sql)
        self.assertIn("ORDER BY COUNT(s.customer_id) DESC", sql)
        self.assertIn("LIMIT 1", sql)
        self.assertTrue(validate_sql(sql).is_valid)

    def test_generates_conditional_percentage(self):
        intent = QueryIntent(
            target_entity="customers",
            metric="services.customer_id",
            aggregation="PERCENTAGE",
            percentage_condition=FilterCondition(
                field="services.internet_service",
                operator="=",
                value="Yes",
            ),
        )

        sql = generate_sql_from_intent(intent)

        self.assertIn(
            "CASE WHEN s.internet_service = 'Yes' THEN 1 ELSE 0 END",
            sql,
        )
        self.assertIn("NULLIF(COUNT(*), 0)", sql)
        self.assertIn("AS percentage_of_customers", sql)
        self.assertNotIn("WHERE s.internet_service", sql)
        self.assertTrue(validate_sql(sql).is_valid)


if __name__ == "__main__":
    unittest.main()
