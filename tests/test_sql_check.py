"""Regression tests for read-only SQL Sentinel."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sql_check import audit, mask_sql  # noqa: E402


def codes(sql: str) -> set[str]:
    return {item["code"] for item in audit(sql)}


class SqlSentinelTests(unittest.TestCase):
    def test_mass_update(self):
        self.assertIn("WRITE_WITHOUT_WHERE", codes("UPDATE x SET active=0;"))
        self.assertNotIn("WRITE_WITHOUT_WHERE", codes("UPDATE x SET active=0 WHERE id=1;"))

    def test_mass_delete(self):
        self.assertIn("WRITE_WITHOUT_WHERE", codes("DELETE FROM x;"))
        self.assertNotIn("WRITE_WITHOUT_WHERE", codes("DELETE FROM x WHERE id=1;"))

    def test_literals_and_comments(self):
        sql = "SELECT '; UPDATE x SET y=1' AS value; -- SELECT *\nSELECT id FROM x;"
        self.assertEqual([], audit(sql))
        self.assertEqual(len(sql), len(mask_sql(sql)))

    def test_performance_patterns(self):
        sql = ("SELECT * FROM x WHERE DATE(created_at) = '2026-10-30' "
               "ORDER BY RAND() LIMIT 10 OFFSET 4000;")
        self.assertTrue({"SELECT_STAR", "FUNCTION_ON_FILTER",
                         "ORDER_BY_RAND", "DEEP_OFFSET"} <= codes(sql))

    def test_leading_wildcard(self):
        self.assertIn("LEADING_WILDCARD", codes("SELECT id FROM x WHERE name LIKE '%test%';"))

    def test_line_number(self):
        self.assertEqual(3, audit("\n\nDELETE FROM x;")[0]["line"])


if __name__ == "__main__":
    unittest.main()
