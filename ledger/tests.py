"""Unit tests for the pure financial functions (Tech Spec §7, PRD §14)."""

from decimal import Decimal
from types import SimpleNamespace

from ledger.financial import cogs, gross_margin, gross_profit


def _line(quantity, unit_cost):
    return SimpleNamespace(quantity=quantity, unit_cost=Decimal(str(unit_cost)))


def _sale(total_amount, lines):
    return SimpleNamespace(total_amount=Decimal(str(total_amount)), lines=lines)


class TestCogs:
    def test_quantity_times_unit_cost(self):
        assert cogs(_line(3, "1200.00")) == Decimal("3600.00")

    def test_single_unit(self):
        assert cogs(_line(1, "100.00")) == Decimal("100.00")

    def test_zero_cost(self):
        assert cogs(_line(5, "0")) == Decimal("0.00")


class TestGrossProfit:
    def test_revenue_minus_sum_of_cogs(self):
        sale = _sale("6000.00", [_line(2, "1000.00"), _line(1, "500.00")])
        assert gross_profit(sale) == Decimal("3500.00")

    def test_no_lines_profit_equals_revenue(self):
        sale = _sale("2000.00", [])
        assert gross_profit(sale) == Decimal("2000.00")


class TestGrossMargin:
    def test_percentage(self):
        sale = _sale("6000.00", [_line(2, "1000.00"), _line(1, "500.00")])
        assert gross_margin(sale) == Decimal("58.33")

    def test_deterministic_when_revenue_is_zero(self):
        sale = _sale("0", [])
        assert gross_margin(sale) == Decimal("0")
