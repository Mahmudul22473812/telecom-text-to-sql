import unittest

from intent_normalizer import normalize_intent
from intent_parser import FilterCondition, QueryIntent


class IntentNormalizerTests(unittest.TestCase):
    def test_how_many_customers_becomes_count(self):
        intent = QueryIntent(
            target_entity="customers",
            selected_fields=["services.total_charges"],
            unresolved_slots=["ranking_metric", "aggregation"],
            ambiguity_reasons=["missing metric", "missing aggregation"],
        )

        normalized = normalize_intent(
            "How many customers are there?",
            intent,
        )

        self.assertEqual(normalized.aggregation, "COUNT")
        self.assertEqual(normalized.metric, "demographics.customer_id")
        self.assertEqual(normalized.selected_fields, [])
        self.assertEqual(normalized.unresolved_slots, [])

    def test_churned_customer_count_uses_resolved_binary_filter(self):
        intent = QueryIntent(
            target_entity="customers",
            filters=[
                FilterCondition(
                    field="status.churn_score",
                    operator=">",
                    value=None,
                )
            ],
            unresolved_slots=["churn_score_threshold"],
            ambiguity_reasons=["missing churn threshold"],
        )

        normalized = normalize_intent(
            "How many customers have churned?",
            intent,
        )

        self.assertEqual(normalized.aggregation, "COUNT")
        self.assertEqual(normalized.metric, "status.customer_id")
        self.assertEqual(len(normalized.filters), 1)
        self.assertEqual(normalized.filters[0].field, "status.churn_value")
        self.assertEqual(normalized.filters[0].value, 1)
        self.assertEqual(normalized.unresolved_slots, [])

    def test_most_customers_uses_explicit_count_ranking(self):
        cases = {
            "Which contract type has the most customers?": (
                "services.contract",
                "services.customer_id",
            ),
            "Which city has the most customers?": (
                "location.city",
                "location.customer_id",
            ),
            "Which payment method is used by the most customers?": (
                "services.payment_method",
                "services.customer_id",
            ),
        }

        for question, (dimension, metric) in cases.items():
            with self.subTest(question=question):
                intent = QueryIntent(
                    unresolved_slots=["ranking_metric"],
                    ambiguity_reasons=["missing ranking metric"],
                )

                normalized = normalize_intent(question, intent)

                self.assertEqual(normalized.selected_fields, [dimension])
                self.assertEqual(normalized.group_by, [dimension])
                self.assertEqual(normalized.aggregation, "COUNT")
                self.assertEqual(normalized.metric, metric)
                self.assertEqual(normalized.order_by, metric)
                self.assertEqual(normalized.order_direction, "DESC")
                self.assertEqual(normalized.limit, 1)
                self.assertEqual(normalized.unresolved_slots, [])

    def test_vague_ranking_remains_ambiguous(self):
        intent = QueryIntent(
            target_entity="customers",
            unresolved_slots=["ranking_metric"],
            ambiguity_reasons=["best is undefined"],
        )

        normalized = normalize_intent(
            "Who are our best customers?",
            intent,
        )

        self.assertEqual(normalized.unresolved_slots, ["ranking_metric"])

    def test_customer_synonyms_and_grouped_count_are_resolved(self):
        intent = QueryIntent(
            filters=[
                FilterCondition(
                    field="services.payment_method",
                    operator="=",
                    value=None,
                )
            ],
            unresolved_slots=["payment_method_value"],
            ambiguity_reasons=["payment method value is missing"],
        )

        normalized = normalize_intent(
            "Which payment option is chosen by the largest number "
            "of subscribers?",
            intent,
        )

        self.assertEqual(normalized.aggregation, "COUNT")
        self.assertEqual(normalized.group_by, ["services.payment_method"])
        self.assertEqual(normalized.filters, [])
        self.assertEqual(normalized.unresolved_slots, [])

    def test_plain_subscriber_count_discards_invented_filter(self):
        intent = QueryIntent(
            filters=[
                FilterCondition(
                    field="status.customer_status",
                    operator="=",
                    value=None,
                )
            ],
            unresolved_slots=["status_value"],
            ambiguity_reasons=["status is missing"],
        )

        normalized = normalize_intent(
            "Give me the total number of subscribers.",
            intent,
        )

        self.assertEqual(normalized.filters, [])
        self.assertEqual(normalized.unresolved_slots, [])
        self.assertEqual(normalized.aggregation, "COUNT")

    def test_explicit_average_removes_invented_metric_threshold(self):
        intent = QueryIntent(
            unresolved_slots=["lifetime_value_threshold"],
            ambiguity_reasons=["lifetime value threshold is missing"],
        )

        normalized = normalize_intent(
            "What is the average lifetime value for people who left "
            "the company?",
            intent,
        )

        self.assertEqual(normalized.aggregation, "AVG")
        self.assertEqual(normalized.metric, "status.cltv")
        self.assertEqual(normalized.unresolved_slots, [])

    def test_explicit_threshold_controls_default_order(self):
        intent = QueryIntent(
            order_by="services.tenure_in_months",
            order_direction="ASC",
            unresolved_slots=["tenure_threshold"],
        )

        normalized = normalize_intent(
            "Show customers with at least 48 months of tenure.",
            intent,
        )

        self.assertEqual(normalized.filters[0].operator, ">=")
        self.assertEqual(normalized.filters[0].value, 48)
        self.assertEqual(normalized.order_direction, "DESC")
        self.assertEqual(normalized.unresolved_slots, [])

    def test_explicit_customer_ranking_overrides_spurious_sum(self):
        intent = QueryIntent(
            aggregation="SUM",
            unresolved_slots=["ranking_metric"],
        )

        normalized = normalize_intent(
            "Show the five customers who generated the greatest total "
            "revenue.",
            intent,
        )

        self.assertIsNone(normalized.aggregation)
        self.assertEqual(normalized.metric, "services.total_revenue")
        self.assertEqual(normalized.order_direction, "DESC")
        self.assertEqual(normalized.limit, 5)
        self.assertEqual(normalized.unresolved_slots, [])

    def test_strongest_customer_discards_invented_threshold(self):
        intent = QueryIntent(
            filters=[
                FilterCondition(
                    field="status.cltv",
                    operator=">",
                    value=None,
                )
            ],
            unresolved_slots=["cltv_threshold"],
            ambiguity_reasons=["CLTV threshold is missing"],
        )

        normalized = normalize_intent(
            "Who are our strongest customers?",
            intent,
        )

        self.assertEqual(normalized.filters, [])
        self.assertEqual(normalized.unresolved_slots, ["ranking_metric"])

    def test_internet_service_percentage_is_fully_represented(self):
        intent = QueryIntent(
            selected_fields=["services.total_charges"],
            unresolved_slots=["internet_service_percentage"],
            ambiguity_reasons=["percentage unclear"],
        )

        normalized = normalize_intent(
            "What percentage of customers have internet service?",
            intent,
        )

        self.assertEqual(normalized.aggregation, "PERCENTAGE")
        self.assertEqual(normalized.metric, "services.customer_id")
        self.assertIsNotNone(normalized.percentage_condition)
        self.assertEqual(
            normalized.percentage_condition.field,
            "services.internet_service",
        )
        self.assertEqual(normalized.percentage_condition.value, "Yes")
        self.assertEqual(normalized.unresolved_slots, [])


if __name__ == "__main__":
    unittest.main()
