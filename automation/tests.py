"""Automation engine (Tech Spec §6) — defaults, CRUD, executions list."""

import pytest

from automation.models import AutomationExecution, AutomationRule
from automation.services import ensure_default_rule


@pytest.mark.django_db
class TestDefaultRule:
    def test_signup_business_gets_default_rule(self, business):
        ensure_default_rule(business)
        assert AutomationRule.objects.filter(business=business).count() == 1
        rule = AutomationRule.objects.get(business=business)
        assert rule.trigger == "payment_confirmed"
        assert rule.action == "notify_merchant"
        assert rule.condition == {"type": "stock_below_threshold"}

    def test_ensure_is_idempotent(self, business):
        ensure_default_rule(business)
        ensure_default_rule(business)
        assert AutomationRule.objects.filter(business=business).count() == 1


@pytest.mark.django_db
class TestAutomationEndpoints:
    def test_list_and_create_rules(self, owner_client, business):
        response = owner_client.get("/automations")
        assert response.status_code == 200
        assert len(response.json()) == 1  # default rule seeded

        response = owner_client.post(
            "/automations",
            {
                "trigger": "payment_confirmed",
                "condition": {"type": "stock_below_threshold"},
                "action": "notify_merchant",
            },
            format="json",
        )
        assert response.status_code == 201
        assert AutomationRule.objects.filter(business=business).count() == 2

    def test_executions_list(self, owner_client, business):
        response = owner_client.get("/automations/executions")
        assert response.status_code == 200
        assert response.json() == []

    def test_cashier_blocked(self, cashier_client):
        assert (
            cashier_client.post(
                "/automations",
                {"trigger": "payment_confirmed", "condition": {}, "action": "x"},
                format="json",
            ).status_code
            == 403
        )


@pytest.mark.django_db
class TestEngineFires:
    def test_low_stock_after_sale_creates_execution(self, owner_client, product):
        product.stock_qty = 6
        product.save(update_fields=["stock_qty"])

        checkout = owner_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": product.id, "quantity": 2}]},
            format="json",
        )
        from payments.services import confirm_payment

        confirm_payment(order_id=checkout.json()["order_id"], amount_bif=500)

        product.refresh_from_db()
        assert product.stock_qty == 4  # below threshold 5 → rule fires
        execution = AutomationExecution.objects.get(rule__business=product.business)
        assert execution.result["triggered"] is True
        assert execution.result["action"] == "notify_merchant"
        assert execution.result["products"][0]["stock_qty"] == 4

    def test_no_execution_when_stock_stays_above_threshold(self, owner_client, product):
        checkout = owner_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": product.id, "quantity": 1}]},
            format="json",
        )
        from payments.services import confirm_payment

        confirm_payment(order_id=checkout.json()["order_id"], amount_bif=250)

        product.refresh_from_db()
        assert product.stock_qty == 9  # still ≥ threshold → no alert
        assert AutomationExecution.objects.count() == 0
