"""Unit tests for the payments services:
- checkout → pending Payment + adapter selection (Tech Spec §3 step 1)
- confirm_payment idempotency on Payment.order_id (PRD §32, AGENTS.md)
- adapter registry / settlement-preference mapping (§5)
"""

import uuid
from decimal import Decimal

import pytest

from payments.adapters import (
    AdapterInvoice,
    AdapterNotInstalled,
    AdapterStatus,
    PaymentRailAdapter,
    get_adapter,
    rails_by_settlement_preference,
    register_adapter,
)
from payments.models import Payment
from payments.services import (
    CheckoutError,
    confirm_payment,
    create_checkout_payment,
    InsufficientStock,
)


@pytest.mark.django_db
class TestAdapters:
    def test_settlement_preference_maps_to_rail(self):
        assert rails_by_settlement_preference("bif_lumicash") == "bitlibera_offramp"
        assert rails_by_settlement_preference("as_is") == "blink_direct"

    def test_register_and_get_adapter(self):
        class _A(PaymentRailAdapter):
            rail = "test_rail"

            def create_invoice(self, *, amount, currency, business, order_id):
                return AdapterInvoice(order_id, "lnbc")

            def get_status(self, order_id):
                return AdapterStatus(status="ok")

        register_adapter(_A())
        assert get_adapter("test_rail").rail == "test_rail"

    def test_get_adapter_raises_when_missing(self):
        with pytest.raises(AdapterNotInstalled):
            get_adapter("bitlibera_onramp")  # never registered for checkout

    def test_checkout_503_via_service(self, owner, product):
        from payments import adapters

        adapters._REGISTRY.clear()
        with pytest.raises(AdapterNotInstalled):
            create_checkout_payment(user=owner, lines=[{"product_id": product.id, "quantity": 1}])


@pytest.mark.django_db
class TestCheckout:
    def test_checkout_creates_pending_payment_with_frozen_lines(self, owner, product):
        payment = create_checkout_payment(
            user=owner, lines=[{"product_id": product.id, "quantity": 2}]
        )

        assert payment.status == Payment.Status.PENDING
        assert payment.rail == "bitlibera_offramp"  # bif_lumicash preference
        assert payment.payment_request.startswith("lnbc1")
        assert payment.total_amount == Decimal("500.00")
        assert payment.lines == [
            {
                "product_id": str(product.id),
                "quantity": 2,
                "unit_price": "250.00",
                "unit_cost": "100.00",
            }
        ]

    def test_checkout_custom_amount(self, owner):
        payment = create_checkout_payment(user=owner, amount=Decimal("1000.00"))
        assert payment.lines == []
        assert payment.total_amount == Decimal("1000.00")

    def test_checkout_requires_lines_or_amount(self, owner):
        with pytest.raises(CheckoutError):
            create_checkout_payment(user=owner)

    def test_checkout_rejects_both(self, owner, product):
        with pytest.raises(CheckoutError):
            create_checkout_payment(
                user=owner,
                lines=[{"product_id": product.id, "quantity": 1}],
                amount=Decimal("10"),
            )

    def test_checkout_rejects_unknown_product(self, owner):
        with pytest.raises(CheckoutError):
            create_checkout_payment(
                user=owner, lines=[{"product_id": str(uuid.uuid4()), "quantity": 1}]
            )

    def test_checkout_rejects_insufficient_stock_at_cart_time(self, owner, product):
        with pytest.raises(InsufficientStock):
            create_checkout_payment(user=owner, lines=[{"product_id": product.id, "quantity": 999}])

    def test_as_is_preference_uses_blink_adapter(self, owner, product):
        owner.business.settlement_preference = "as_is"
        owner.business.blink_username = "alias@blink.sats"
        owner.business.save(update_fields=["settlement_preference", "blink_username"])

        payment = create_checkout_payment(
            user=owner, lines=[{"product_id": product.id, "quantity": 1}]
        )
        assert payment.rail == "blink_direct"


@pytest.mark.django_db
class TestConfirmPayment:
    def test_first_confirm_creates_event_and_links_payment(self, owner, product):
        payment = create_checkout_payment(
            user=owner, lines=[{"product_id": product.id, "quantity": 1}]
        )

        event = confirm_payment(order_id=payment.order_id, amount_bif=250)

        assert event.reference == payment.order_id
        assert event.status == "confirmed"
        payment.refresh_from_db()
        assert payment.status == Payment.Status.CONFIRMED
        assert payment.financial_event_id == event.id

    def test_duplicate_confirm_returns_same_event(self, owner, product):
        payment = create_checkout_payment(
            user=owner, lines=[{"product_id": product.id, "quantity": 1}]
        )
        order_id = payment.order_id

        first = confirm_payment(order_id=order_id, amount_bif=250)
        second = confirm_payment(order_id=order_id, amount_bif=250)
        third = confirm_payment(order_id=order_id, amount_bif=250)

        assert second.id == first.id
        assert third.id == first.id
        from ledger.models import FinancialEvent

        assert FinancialEvent.objects.filter(reference=order_id).count() == 1

    def test_confirm_unknown_order_raises(self, db):
        with pytest.raises(Payment.DoesNotExist):
            confirm_payment(order_id="does-not-exist")


@pytest.mark.django_db
class TestPaymentStatusEndpoint:
    def test_status_polls_and_confirms_when_paid(self, owner_client, owner, product):
        payment = create_checkout_payment(
            user=owner, lines=[{"product_id": product.id, "quantity": 1}]
        )
        response = owner_client.get(f"/payments/{payment.id}/status")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "confirmed"  # demo adapter reports paid immediately
        payment.refresh_from_db()
        assert payment.status == Payment.Status.CONFIRMED
        assert payment.financial_event_id is not None

    def test_status_returns_pending_when_failed_confirmation(self, owner_client, owner, product):
        payment = create_checkout_payment(
            user=owner, lines=[{"product_id": product.id, "quantity": 1}]
        )

        class _PendingAdapter(PaymentRailAdapter):
            rail = "bitlibera_offramp"

            def create_invoice(self, *, amount, currency, business, order_id):
                return AdapterInvoice(order_id, "lnbc")

            def get_status(self, order_id):
                return AdapterStatus(status="pending")

        register_adapter(_PendingAdapter())
        response = owner_client.get(f"/payments/{payment.id}/status")
        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    def test_status_404_for_other_business_payment(self, owner_client, business, owner):
        other_business = type(business).objects.create(name="Other", owner=owner)
        payment = Payment.objects.create(
            business=other_business, rail="bitlibera_offramp", order_id="other-order"
        )
        response = owner_client.get(f"/payments/{payment.id}/status")
        assert response.status_code == 404


@pytest.mark.django_db
class TestPaymentStatusExpired:
    def test_status_marks_expired_when_adapter_reports_expired(self, owner_client, owner, product):
        payment = create_checkout_payment(
            user=owner, lines=[{"product_id": product.id, "quantity": 1}]
        )

        class _ExpiredAdapter(PaymentRailAdapter):
            rail = "bitlibera_offramp"

            def create_invoice(self, *, amount, currency, business, order_id):
                return AdapterInvoice(order_id, "lnbc")

            def get_status(self, order_id):
                return AdapterStatus(status="expired")

        register_adapter(_ExpiredAdapter())
        response = owner_client.get(f"/payments/{payment.id}/status")

        assert response.status_code == 200
        assert response.json()["status"] == "expired"
        payment.refresh_from_db()
        assert payment.status == Payment.Status.EXPIRED
        assert payment.financial_event_id is None


@pytest.mark.django_db
class TestOnramp:
    PHONE = "+25771111111"

    def _pending_payment(self, owner, product):
        return create_checkout_payment(
            user=owner, lines=[{"product_id": product.id, "quantity": 1}]
        )

    def test_request_otp_returns_status_and_demo_otp(self, owner_client, owner, product):
        self._pending_payment(owner, product)
        response = owner_client.post(
            "/payments/onramp/request-otp",
            {"customer_phone": self.PHONE, "amount": "250.00"},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "otp_sent"
        assert len(body["demo_otp"]) == 6

    def test_confirm_otp_confirms_payment_and_returns_receipt(self, owner_client, owner, product):
        payment = self._pending_payment(owner, product)
        otp = self._request_otp(owner_client)
        response = owner_client.post(
            "/payments/onramp/confirm",
            {
                "customer_phone": self.PHONE,
                "amount": "250.00",
                "otp": otp,
                "order_id": payment.order_id,
            },
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["order_id"] == payment.order_id
        assert body["status"] == "confirmed"
        assert body["receipt"] is not None
        payment.refresh_from_db()
        assert payment.status == Payment.Status.CONFIRMED
        assert payment.financial_event_id is not None

    def test_confirm_otp_is_idempotent(self, owner_client, owner, product):
        payment = self._pending_payment(owner, product)
        otp = self._request_otp(owner_client)
        payload = {
            "customer_phone": self.PHONE,
            "amount": "250.00",
            "otp": otp,
            "order_id": payment.order_id,
        }
        first = owner_client.post("/payments/onramp/confirm", payload, format="json")
        second = owner_client.post("/payments/onramp/confirm", payload, format="json")

        assert first.json()["status"] == "confirmed"
        assert second.json()["status"] == "confirmed"
        from ledger.models import FinancialEvent

        assert FinancialEvent.objects.filter(reference=payment.order_id).count() == 1

    def test_confirm_otp_rejects_wrong_otp(self, owner_client, owner, product):
        payment = self._pending_payment(owner, product)
        self._request_otp(owner_client)
        response = owner_client.post(
            "/payments/onramp/confirm",
            {
                "customer_phone": self.PHONE,
                "amount": "250.00",
                "otp": "999999",
                "order_id": payment.order_id,
            },
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_otp"
        payment.refresh_from_db()
        assert payment.status == Payment.Status.PENDING
        assert payment.financial_event_id is None

    def test_confirm_otp_404_for_unknown_order(self, owner_client, owner, product):
        self._pending_payment(owner, product)
        response = owner_client.post(
            "/payments/onramp/confirm",
            {
                "customer_phone": self.PHONE,
                "amount": "250.00",
                "otp": "123456",
                "order_id": "does-not-exist",
            },
            format="json",
        )
        assert response.status_code == 404

    def test_cashier_can_use_onramp_endpoints(self, cashier_client, owner, product):
        payment = self._pending_payment(owner, product)
        otp = self._request_otp(cashier_client)
        response = cashier_client.post(
            "/payments/onramp/confirm",
            {
                "customer_phone": self.PHONE,
                "amount": "250.00",
                "otp": otp,
                "order_id": payment.order_id,
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "confirmed"

    def test_request_otp_503_when_adapter_missing(self, owner_client, owner, product):
        self._pending_payment(owner, product)
        from payments import adapters

        adapters._ONRAMP_REGISTRY.clear()
        response = owner_client.post(
            "/payments/onramp/request-otp",
            {"customer_phone": self.PHONE, "amount": "250.00"},
            format="json",
        )
        assert response.status_code == 503
        assert response.json()["code"] == "adapter_not_installed"

    def _request_otp(self, client):
        response = client.post(
            "/payments/onramp/request-otp",
            {"customer_phone": self.PHONE, "amount": "250.00"},
            format="json",
        )
        assert response.status_code == 200
        return response.json()["demo_otp"]
