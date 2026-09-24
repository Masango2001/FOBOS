"""Automation engine (Tech Spec §6, §3 step 4).

Evaluates active rules after a sale transaction commits. MVP ships exactly one
rule type — stock threshold → notify merchant. No condition DSL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from ledger.models import FinancialEvent

DEFAULT_TRIGGER: Final = "payment_confirmed"
DEFAULT_CONDITION: Final = {"type": "stock_below_threshold"}
DEFAULT_ACTION: Final = "notify_merchant"

DEFAULT_RULE: Final = {
    "trigger": DEFAULT_TRIGGER,
    "condition": DEFAULT_CONDITION,
    "action": DEFAULT_ACTION,
}


def ensure_default_rule(business) -> None:
    """Create the demo rule once per business (called at signup and lazily on read)."""
    from .models import AutomationRule

    if not AutomationRule.objects.filter(business=business, trigger=DEFAULT_TRIGGER).exists():
        AutomationRule.objects.create(
            business=business,
            trigger=DEFAULT_TRIGGER,
            condition=DEFAULT_CONDITION,
            action=DEFAULT_ACTION,
            active=True,
        )


def run_automation_for_event(event: FinancialEvent) -> list:
    """Evaluate active rules against the confirmed event + resulting state (§3 step 4)."""
    from .models import AutomationExecution, AutomationRule

    ensure_default_rule(event.business)  # demo rule always present for the driven chain
    from sales.models import Sale

    sale = Sale.objects.filter(financial_event=event).first()
    if sale is None:
        return []

    executions = []
    rules = AutomationRule.objects.filter(
        business=event.business, active=True, trigger=DEFAULT_TRIGGER
    )
    for rule in rules:
        condition = rule.condition or {}
        if condition.get("type") != "stock_below_threshold":
            continue  # unknown condition types are Phase 2 (no DSL in the MVP)

        low_stock = []
        for line in sale.sale_lines.select_related("product"):
            product = line.product
            if product.low_stock:
                low_stock.append(
                    {
                        "id": product.id,
                        "name": product.name,
                        "stock_qty": product.stock_qty,
                        "stock_threshold": product.stock_threshold,
                    }
                )
        if not low_stock:
            continue

        execution = AutomationExecution.objects.create(
            rule=rule,
            financial_event=event,
            result={
                "triggered": True,
                "action": rule.action,
                "condition": condition,
                "products": low_stock,
                "sale_id": sale.id,
            },
        )
        executions.append(execution)
    return executions
