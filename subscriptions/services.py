"""Subscription lifecycle services (doc §39–41, §53–56).

- `create_trial` grants the 3-day free trial at business signup (§55) —
  idempotent on the business so repeated signup calls never stack trials.
  The client works with a TRIAL subscription and an explicit feature-gated
  ~30% access until it pays (§53). The trial does not require a plan to exist.
- `activate_from_payment` flips Payment=PAID (purpose=subscription, doc §41)
  into Subscription=ACTIVE. It is idempotent on the Payment: a duplicate confirm
  call (webhook retry) returns the existing Subscription and never creates a
  second one.
- `create_subscription_payment` is owned by `payments/` (it builds the Payment);
  `subscriptions/` only reacts to its confirmation.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from accounts.models import Business
    from payments.models import Payment

TRIAL_DAYS = 3

__all__ = ["TRIAL_DAYS", "create_trial", "activate_from_payment"]


class SubscriptionError(Exception):
    """Validation failure for a SaaS subscription (HTTP 400)."""

    def __init__(self, message: str, code: str = "subscription_error") -> None:
        super().__init__(message)
        self.code = code


@transaction.atomic
def create_trial(*, business: Business):
    """Grant the 3-day trial at signup (doc §55) — idempotent on the business.

    Only creates a trial when no current TRIAL/ACTIVE subscription exists for
    the business, so the auto-trial at signup is always a single call.
    """
    from .models import Subscription

    now = timezone.now()
    existing = Subscription.objects.filter(business=business).exclude(
        status__in=[Subscription.Status.EXPIRED, Subscription.Status.CANCELLED]
    )
    if existing.exists():
        return existing.first()

    return Subscription.objects.create(
        business=business,
        status=Subscription.Status.TRIAL,
        started_at=now,
        expires_at=now + timedelta(days=TRIAL_DAYS),
    )


@transaction.atomic
def activate_from_payment(*, payment: Payment):
    """Activate the SaaS subscription once a subscription payment is PAID (§41).

    Idempotent on the Payment: a duplicate confirm call returns the existing
    Subscription and never creates a second one. Activation only happens AFTER
    a reliable, idempotent payment confirmation (doc §55 — Payment=PAID triggers
    Subscription=ACTIVE, never before).
    """
    from .models import Subscription, SubscriptionOffer

    if payment.purpose != "subscription":
        raise SubscriptionError("Payment is not a subscription purchase.", code="not_subscription")

    business = payment.business
    existing = Subscription.objects.filter(business=business, payment=payment).first()
    if existing is not None:
        return existing

    offer = None
    for line in payment.lines or []:
        offer_id = line.get("offer_id")
        if offer_id:
            offer = SubscriptionOffer.objects.filter(pk=offer_id).first()
            break

    now = timezone.now()
    months = (offer.duration_months if offer else 1) or 1

    return Subscription.objects.create(
        business=business,
        plan=offer.plan if offer is not None else None,
        offer=offer,
        payment=payment,
        status=Subscription.Status.ACTIVE,
        started_at=now,
        expires_at=now + timedelta(days=months * 30),
    )
