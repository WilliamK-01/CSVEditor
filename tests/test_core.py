import unittest
from decimal import Decimal

from core import parse_decimal, normalize_date, try_parse_line, money2


class CoreTests(unittest.TestCase):
    def test_parse_decimal_us(self):
        self.assertEqual(parse_decimal("1,234.56"), Decimal("1234.56"))

    def test_parse_decimal_eu(self):
        self.assertEqual(parse_decimal("1.234,56"), Decimal("1234.56"))

    def test_parse_decimal_symbols(self):
        self.assertEqual(parse_decimal("$ -99.9"), Decimal("-99.9"))

    def test_normalize_date(self):
        self.assertEqual(normalize_date("31-12-2025"), "2025/12/31")
        self.assertEqual(normalize_date("20251231"), "2025/12/31")

    def test_try_parse_line_csv(self):
        tx = try_parse_line("2025-01-10,Coffee,-3.50")
        self.assertIsNotNone(tx)
        self.assertEqual(tx.date, "2025/01/10")
        self.assertEqual(tx.description, "Coffee")
        self.assertEqual(tx.amount, Decimal("-3.50"))

    def test_try_parse_line_tab(self):
        tx = try_parse_line("01/11/2025\tSalary\t1200")
        self.assertIsNotNone(tx)
        self.assertEqual(tx.date, "2025/11/01")

    def test_money_round(self):
        self.assertEqual(money2(Decimal("1.005")), Decimal("1.01"))


if __name__ == "__main__":
    unittest.main()
