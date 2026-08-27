import unittest
from decimal import Decimal

from evaluation.evaluate_end_to_end import (
    evaluate_sql_safety,
    percentile,
    rows_equal,
)


class EndToEndEvaluatorTests(unittest.TestCase):
    def test_rows_equal_supports_numeric_tolerance(self):
        self.assertTrue(
            rows_equal(
                [(Decimal("74.4400"),)],
                [(74.44,)],
            )
        )

    def test_rows_equal_can_ignore_order(self):
        self.assertTrue(
            rows_equal(
                [("Month-to-Month", 10), ("Two Year", 5)],
                [("Two Year", 5), ("Month-to-Month", 10)],
                order_sensitive=False,
            )
        )

    def test_rows_equal_detects_different_results(self):
        self.assertFalse(
            rows_equal([(10,)], [(11,)])
        )

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], 0.95), 5)

    def test_safety_suite_passes(self):
        result = evaluate_sql_safety()

        self.assertEqual(result["safe_acceptance_rate"], 1.0)
        self.assertEqual(result["unsafe_rejection_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
