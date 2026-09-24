"""Checkout→ledger chain: atomicity, idempotency, and read endpoints (Tech Spec §3/§4)."""

from decimal import Decimal

import pytest

from ledger.models import FinancialEvent, LedgerEntry
from payments.models import Payment
from sales.models import Receipt, Sale, SaleLine


@pytest.mark.django_db
class TestCheckout:
    def test_checkout_creates_pending_payment(self, owner_client, product):
        response = owner_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": product.id, "quantity": 1}]},
            format="json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["rail"] == "bitlibera_offramp"
        assert body["status"] == "pending"
        assert body["payment_request"].startswith("lnbc1")
        assert body["amount"] == "250.00"

        payment = Payment.objects.get(order_id=body["order_id"])
        assert payment.status == Payment.Status.PENDING
        assert payment.lines[0]["unit_price"] == "250.00"
        assert payment.lines[0]["unit_cost"] == "100.00"

    def test_checkout_custom_amount(self, owner_client, product):
        response = owner_client.post(
            "/cart/checkout", {"amount": "5000.00", "currency": "BIF"}, format="json"
        )
        assert response.status_code == 201
        assert response.json()["amount"] == "5000.00"
        payment = Payment.objects.get(order_id=response.json()["order_id"])
        assert payment.lines == []

    def test_checkout_requires_lines_or_amount(self, owner_client):
        response = owner_client.post("/cart/checkout", {}, format="json")
        assert response.status_code == 400

    def test_checkout_rejects_unknown_product(self, owner_client):
        response = owner_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": 99999, "quantity": 1}]},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "unknown_product"

    def test_checkout_rejects_insufficient_stock(self, owner_client, product):
        response = owner_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": product.id, "quantity": 999}]},
            format="json",
        )
        assert response.status_code == 409
        assert response.json()["code"] == "insufficient_stock"

    def test_cashier_can_checkout(self, cashier_client, product):
        response = cashier_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": product.id, "quantity": 1}]},
            format="json",
        )
        assert response.status_code == 201

    def test_checkout_503_when_adapter_missing(self, owner_client, product):
        from payments import adapters

        adapters._REGISTRY.clear()
        response = owner_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": product.id, "quantity": 1}]},
            format="json",
        )
        assert response.status_code == 503
        assert response.json()["code"] == "adapter_not_installed"


@pytest.mark.django_db
class TestConfirmPayment:
    def _checkout(self, owner_client, product, qty=1):
        response = owner_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": product.id, "quantity": qty}]},
            format="json",
        )
        return response.json()

    def test_confirmation_writes_full_chain_atomically(self, owner_client, product):
        data = self._checkout(owner_client, product)

        event = confirm(data["order_id"], product)

        assert event.status == FinancialEvent.Status.CONFIRMED
        payment = Payment.objects.get(order_id=data["order_id"])
        assert payment.status == Payment.Status.CONFIRMED
        assert payment.financial_event_id == event.id

        sale = Sale.objects.get(financial_event=event)
        assert sale.total_amount == Decimal("250.00")
        line = SaleLine.objects.get(sale=sale)
        assert (line.quantity, line.unit_price, line.unit_cost) == (
            1,
            Decimal("250.00"),
            Decimal("100.00"),
        )

        entries = {}
        for entry in LedgerEntry.objects.filter(financial_event=event):
            entries[(entry.type, entry.account)] = entry.amount
        assert entries == {
            (LedgerEntry.MovementType.CREDIT, "REVENUE"): Decimal("250.00"),
            (LedgerEntry.MovementType.DEBIT, "COGS"): Decimal("100.00"),
        }

        product.refresh_from_db()
        assert product.stock_qty == 9
        assert Receipt.objects.filter(sale=sale).exists()

    def test_duplicate_confirmation_is_idempotent(self, owner_client, product):
        """PRD §32 / AGENTS.md: a duplicate call must not duplicate financial records."""
        data = self._checkout(owner_client, product)
        order_id = data["order_id"]

        first = confirm(order_id, product)
        assert first is not None
        duplicate = confirm(order_id, product)

        assert duplicate.id == first.id
        payment = Payment.objects.get(order_id=order_id)
        assert payment.financial_event_id == first.id
        assert FinancialEvent.objects.filter(reference=order_id).count() == 1
        assert Sale.objects.filter(financial_event=first).count() == 1
        assert SaleLine.objects.all().count() == 1
        assert LedgerEntry.objects.filter(financial_event=first).count() == 2

        product.refresh_from_db()
        assert product.stock_qty == 9  # decremented exactly once

    def test_duplicate_event_for_same_order_does_not_create_duplicate_sale(
        self, owner_client, product
    ):
        data = self._checkout(owner_client, product)
        order_id = data["order_id"]
        payment = Payment.objects.get(order_id=order_id)
        first_event = confirm(order_id, product)
        assert Sale.objects.filter(financial_event=first_event).count() == 1

        # Simulate Dev B sending a second (duplicate) FinancialEvent for the same order.
        second_event = FinancialEvent.objects.create(
            business=payment.business,
            type=FinancialEvent.EventType.PAYMENT_CONFIRMED,
            amount=Decimal("250.00"),
            currency="BIF",
            source=payment.rail,
            status=FinancialEvent.Status.CONFIRMED,
            reference=order_id,
        )
        # The handler must reuse the existing sale, not create a second one.
        from sales.services import handle_financial_event

        result = handle_financial_event(second_event)
        assert result.financial_event_id == first_event.id
        assert Sale.objects.count() == 1
        assert SaleLine.objects.count() == 1
        product.refresh_from_db()
        assert product.stock_qty == 9

    def test_confirmation_is_atomic_when_stock_insufficient(self, owner_client, product):
        """PRD §27 / AGENTS.md: all-or-nothing — no partial business state."""
        data = self._checkout(owner_client, product, qty=1)
        order_id = data["order_id"]
        payment = Payment.objects.get(order_id=order_id)

        # Simulate stock dropping below the cart quantity between cart and confirm.
        product.stock_qty = 0
        product.save(update_fields=["stock_qty"])

        from sales.services import InsufficientStockError

        with pytest.raises(InsufficientStockError):
            confirm(order_id, product)

        payment.refresh_from_db()
        assert payment.status == Payment.Status.PENDING
        assert payment.financial_event_id is None
        assert FinancialEvent.objects.filter(reference=order_id).count() == 0
        assert Sale.objects.count() == 0
        assert SaleLine.objects.count() == 0
        assert LedgerEntry.objects.filter(business=product.business).count() == 0
        assert Receipt.objects.count() == 0


@pytest.mark.django_db
class TestReadEndpoints:
    def _sell(self, owner_client, product, qty=1):
        checkout = owner_client.post(
            "/cart/checkout",
            {"lines": [{"product_id": product.id, "quantity": qty}]},
            format="json",
        )
        confirm(checkout.json()["order_id"], product)

    def test_dashboard_returns_real_computed_data(self, owner_client, product):
        self._sell(owner_client, product)

        response = owner_client.get("/dashboard")
        assert response.status_code == 200
        body = response.json()
        assert body["today_sales_count"] == 1
        assert body["revenue"] == "250.00"
        assert body["cogs"] == "100.00"
        assert body["gross_profit"] == "150.00"
        assert body["gross_margin"] == "60.00"
        assert body["net_cashflow"] == "150.00"

    def test_ledger_lists_entries(self, owner_client, product):
        self._sell(owner_client, product)

        response = owner_client.get("/ledger")
        assert response.status_code == 200
        accounts = {item["account"] for item in response.json()}
        assert accounts == {"REVENUE", "COGS"}

    def test_inventory_endpoint(self, owner_client, product):
        response = owner_client.get("/inventory")
        assert response.status_code == 200
        item = response.json()[0]
        assert item["inventory_value"] == 1000  # 10 × 100
        assert item["low_stock"] is False

    def test_cashier_blocked_from_financial_reads(self, cashier_client):
        for path in ("/dashboard", "/ledger", "/inventory", "/automations"):
            response = cashier_client.get(path)
            assert response.status_code == 403

    def test_owner_alerts_show_triggered_stock_warning(self, owner_client, product):
        product.stock_qty = 6  # after selling 2 → 4 < threshold 5
        product.save(update_fields=["stock_qty"])

        self._sell(owner_client, product, qty=2)

        from automation.models import AutomationExecution

        product.refresh_from_db()
        assert product.stock_qty == 4
        execution = AutomationExecution.objects.get(rule__business=product.business)
        assert execution.result["triggered"] is True

        response = owner_client.get("/dashboard")
        assert response.status_code == 200
        alerts = response.json()["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["products"][0]["stock_qty"] == 4


def confirm(order_id, product):
    from payments.services import confirm_payment

    return confirm_payment(
        order_id=order_id,
        amount_bif=250,
        actor="alice@fobos.test",
    )
