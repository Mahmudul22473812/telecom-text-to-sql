import unittest

from telecom_text_to_sql.sql_validator import remove_sql_comments, validate_sql


class SQLValidatorTests(unittest.TestCase):
    def assert_valid(self, sql: str) -> None:
        result = validate_sql(sql)
        self.assertTrue(result.is_valid, result.errors)

    def assert_invalid(self, sql: str) -> None:
        result = validate_sql(sql)
        self.assertFalse(result.is_valid)
        self.assertTrue(result.errors)

    def test_accepts_generated_select(self):
        self.assert_valid(
            """
            SELECT s.customer_id, s.total_revenue
            FROM services s
            ORDER BY s.total_revenue DESC
            LIMIT 20;
            """
        )

    def test_accepts_keyword_and_semicolon_inside_string(self):
        self.assert_valid("SELECT 'DROP TABLE status;';")

    def test_ignores_comments_when_checking_keywords(self):
        self.assert_valid(
            "-- DROP TABLE status;\nSELECT customer_id FROM services;"
        )

    def test_rejects_non_select_statement(self):
        self.assert_invalid("DROP TABLE services;")

    def test_rejects_multiple_statements(self):
        self.assert_invalid(
            "SELECT * FROM services; DROP TABLE status;"
        )

    def test_rejects_select_into(self):
        self.assert_invalid("SELECT * INTO services_copy FROM services;")

    def test_rejects_postgresql_file_access(self):
        self.assert_invalid("SELECT pg_read_file('/etc/passwd');")

    def test_rejects_row_locking(self):
        self.assert_invalid("SELECT * FROM services FOR UPDATE;")

    def test_rejects_unterminated_literal(self):
        self.assert_invalid("SELECT 'unfinished;")

    def test_remove_comments_preserves_markers_inside_strings(self):
        sql = "SELECT '--not a comment' /* comment */ FROM services;"
        cleaned = remove_sql_comments(sql)

        self.assertIn("'--not a comment'", cleaned)
        self.assertNotIn("/* comment */", cleaned)


if __name__ == "__main__":
    unittest.main()
