"""Tests for the SaaS layer (doc §39–56): 3-day trial, offer pricing, activation
on a PAID subscription Payment, feature gates and the public/authenticated API.

The demo adapters registered by conftest are what let `create_subscription_payment`
build a Payment — there is no external network in these tests.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from payments.models import Payment
from payments.services import confirm_payment, create_subscription_payment

from .models import Plan, Subscription, SubscriptionOffer
from .permissions import FULL_FEATURES, TRIAL_FEATURES, feature_whitelist, has_business_feature
from .services import TRIAL_DAYS, SubscriptionError, activate_from_payment, create_trial


@pytest.fixture
def plan(db):
    return Plan.objects.create(name="Starter", unit_price=Decimal("50000.00"))


@pytest.fixture
def offer(db, plan):
    return SubscriptionOffer.objects.create(
        plan=plan,
        duration_months=3,
        discount_rate=Decimal("0.1000"),
    )


@pytest.mark.django_db
class TestTrial:
    def test_granted_at_signup_with_3_day_window(self, business):
        subscription = create_trial(business=business)

        assert subscription.status == Subscription.Status.TRIAL
        assert subscription.started_at is not None
        assert subscription.expires_at == subscription.started_at + timedelta(days=TRIAL_DAYS)
        assert subscription.payment is None

    def test_idempotent_on_business(self, business):
        first = create_trial(business=business)
        second = create_trial(business=business)

        assert first.pk == second.pk
        assert business.subscriptions.count() == 1

    def test_expired_trial_reopens_with_fresh_trial(self, business):
        subscription = create_trial(business=business)
        subscription.status = Subscription.Status.EXPIRED
        subscription.expires_at = timezone.now() - timedelta(days=1)
        subscription.save()

        fresh = create_trial(business=business)
        assert fresh.status == Subscription.Status.TRIAL
        assert fresh.pk != subscription.pk
        assert business.subscriptions.count() == 2


@pytest.mark.django_db
class TestActivateFromPayment:
    def _payment(self, business, offer, purpose="subscription"):
        lines = [{"offer_id": str(offer.id)}] if offer is not None else []
        return Payment.objects.create(
            business=business,
            rail=Payment.Rail.BITLIBERA_OFFRAMP,
            order_id="sub-order-1",
            payment_request="lnbc1",
            lines=lines,
            currency="BIF",
            amount_bif=int(offer.final_price) if offer is not None else 0,
            purpose=purpose,
            status=Payment.Status.PENDING,
        )

    def test_activates_with_offer_and_months(self, business, offer, plan):
        payment = self._payment(business, offer)
        subscription = activate_from_payment(payment=payment)

        assert subscription.status == Subscription.Status.ACTIVE
        assert subscription.plan == plan
        assert subscription.offer == offer
        assert subscription.payment == payment
        expected_expiry = subscription.started_at + timedelta(days=offer.duration_months * 30)
        assert subscription.expires_at == expected_expiry

    def test_idempotent_on_payment(self, business, offer):
        payment = self._payment(business, offer)
        first = activate_from_payment(payment=payment)
        second = activate_from_payment(payment=payment)

        assert first.pk == second.pk
        assert business.subscriptions.count() == 1

    def test_defaults_to_one_month_without_offer(self, business):
        payment = self._payment(business, None)

        subscription = activate_from_payment(payment=payment)
        assert subscription.status == Subscription.Status.ACTIVE
        assert subscription.plan is None
        assert subscription.expires_at == subscription.started_at + timedelta(days=30)

    def test_rejects_non_subscription_payment(self, business, offer):
        payment = self._payment(business, offer, purpose="checkout")
        with pytest.raises(SubscriptionError) as excinfo:
            activate_from_payment(payment=payment)
        assert excinfo.value.code == "not_subscription"


@pytest.mark.django_db
class TestFeatureGates:
    def test_whitelist_lengths(self):
        assert len(TRIAL_FEATURES) < len(FULL_FEATURES)
        assert TRIAL_FEATURES < FULL_FEATURES

    def test_whitelist_by_status(self):
        assert feature_whitelist("active") == sorted(FULL_FEATURES)
        assert feature_whitelist("trial") == sorted(TRIAL_FEATURES)
        assert feature_whitelist("expired") == []
        assert feature_whitelist("cancelled") == []

    def test_has_feature_for_trial_and_active(self, business):
        create_trial(business=business)
        assert has_business_feature(business, "pos") is True
        assert has_business_feature(business, "automation_rules") is False

    def test_no_feature_after_expiry(self, business):
        subscription = create_trial(business=business)
        subscription.expires_at = timezone.now() - timedelta(seconds=1)
        subscription.save(update_fields=["expires_at"])

        assert has_business_feature(business, "pos") is False

    def test_no_feature_without_subscription(self, business):
        assert has_business_feature(business, "pos") is False


@pytest.mark.django_db
class TestSubscriptionApi:
    def test_catalog_requires_auth_and_lists_data(self, auth_client, owner_client, plan, offer):
        plans = owner_client.get("/plans/")
        offers = owner_client.get("/offers/")

        assert plans.status_code == 200
        assert offers.status_code == 200
        assert plans.json()[0]["name"] == "Starter"
        assert offers.json()[0]["id"] == str(offer.id)
        assert offers.json()[0]["duration_months"] == 3
        # Consistent with the global IsAuthenticated default.
        assert auth_client.get("/plans/").status_code == 401

    def test_my_plan_requires_auth(self, auth_client):
        assert auth_client.get("/my/plan/").status_code == 401

    def test_my_plan_shows_trial_and_features(self, owner_client, business):
        create_trial(business=business)
        response = owner_client.get("/my/plan/")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "trial"
        assert set(body["features"]) == TRIAL_FEATURES

    def test_activate_creates_subscription_payment(self, owner_client, owner, offer):
        response = owner_client.post("/activate/", {"offer_id": str(offer.id)}, format="json")

        assert response.status_code == 201
        order_id = response.json()["payment"]["order_id"]
        payment = Payment.objects.get(order_id=order_id)
        assert payment.purpose == Payment.Purpose.SUBSCRIPTION
        assert payment.amount_bif == int(offer.final_price)
        assert payment.status == Payment.Status.PENDING
        assert response.json()["features"] == sorted(FULL_FEATURES)

    def test_activate_rejects_unknown_offer(self, owner_client):
        response = owner_client.post(
            "/activate/", {"offer_id": "00000000-0000-0000-0000-000000000000"}, format="json"
        )
        assert response.status_code == 400

    def test_final_price_formula(self, offer):
        # FinalPrice(N) = P×N×(1−D(N)) — doc §54.
        expected = Decimal("50000.00") * 3 * (1 - Decimal("0.1000"))
        assert offer.final_price == expected


@pytest.mark.django_db
class TestSubscriptionPaymentFlow:
    def test_confirm_payment_activates_subscription(self, owner, business, offer):
        payment = create_subscription_payment(
            user=owner, offer_id=str(offer.id), amount=offer.final_price
        )

        event = confirm_payment(order_id=payment.order_id, amount_bif=payment.amount_bif)

        payment.refresh_from_db()
        assert payment.status == Payment.Status.PAID
        assert payment.financial_event_id == event.id

        subscription = Subscription.objects.get(business=business, payment=payment)
        assert subscription.status == Subscription.Status.ACTIVE

        # A subscription Payment settles no cart: no Sale, no ledger entries.
        from ledger.models import LedgerEntry
        from sales.models import Sale

        assert not Sale.objects.filter(financial_event=event).exists()
        assert not LedgerEntry.objects.filter(financial_event=event).exists()

    def test_confirm_payment_idempotent_for_subscription(self, owner, offer):
        payment = create_subscription_payment(
            user=owner, offer_id=str(offer.id), amount=offer.final_price
        )
        first = confirm_payment(order_id=payment.order_id, amount_bif=payment.amount_bif)
        second = confirm_payment(order_id=payment.order_id, amount_bif=payment.amount_bif)

        assert first.id == second.id
        from .models import Subscription

        assert Subscription.objects.filter(payment_id=payment.id).count() == 1
