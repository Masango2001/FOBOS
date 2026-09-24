"""Deterministic, side-effect-free financial calculations (Tech Spec §7, PRD §14)."""

from decimal import Decimal
from typing import Any

ZERO = Decimal("0")


def cogs(sale_line: Any) -> Decimal:
    """COGS of one sale line = quantity × unit cost."""
    quantity = Decimal(str(getattr(sale_line, "quantity")))
    unit_cost = Decimal(str(getattr(sale_line, "unit_cost") or 0))
    return (quantity * unit_cost).quantize(Decimal("0.01"))


def gross_profit(sale: Any) -> Decimal:
    """Revenue - total COGS across the sale's lines."""
    total_amount = Decimal(str(getattr(sale, "total_amount") or 0))
    lines = getattr(sale, "lines", None) or []
    total_cogs = sum((cogs(line) for line in lines), ZERO)
    return (total_amount - total_cogs).quantize(Decimal("0.01"))


def gross_margin(sale: Any) -> Decimal:
    """Gross profit ÷ revenue × 100. Deterministic (0 when revenue is 0)."""
    total_amount = Decimal(str(getattr(sale, "total_amount") or 0))
    if total_amount == 0:
        return ZERO
    profit = gross_profit(sale)
    return ((profit / total_amount) * Decimal("100")).quantize(Decimal("0.01"))
