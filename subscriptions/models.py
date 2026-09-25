"""Subscription domain models (Tech Spec §39–41, §53–56; doc §54 FinalPrice).

Field names are contract — never rename. Enums mirror the canonical statuses the
API returns to clients (doc §5.4): Subscription = TRIAL | ACTIVE | EXPIRED |
CANCELLED; a Payment that purchased one has purpose=subscription and the offer
snapshot the subscription layer activates from on confirmation (§41: Payment=PAID
→ Subscription=ACTIVE).
"""

import uuid

from django.db import models

from accounts.models import Business
from payments.models import Payment


class Plan(models.Model):
    """A SaaS plan sold to businesses (doc §39) — e.g. "Starter".

    `unit_price` is the monthly list price in BIF; offers layer a discount on top
    (doc §54 FinalPrice(N) = P×N×(1−D(N))).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    unit_price = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["unit_price", "name"]

    def __str__(self) -> str:
        return self.name


class SubscriptionOffer(models.Model):
    """A purchasable offer: a plan bought for `duration_months` at `discount_rate`.

    Discount is a rate (0 ≤ rate < 1) applied over N months — doc §54:
    FinalPrice(N) = P×N×(1−D(N)). `discount_rate=0` means no discount.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="offers")
    duration_months = models.PositiveIntegerField(default=1)
    discount_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-discount_rate"]
        indexes = [models.Index(fields=["plan", "is_active"])]

    @property
    def final_price(self):
        """FinalPrice(N) = P×N×(1−D) (doc §54) — Decimal, not rounded."""
        from decimal import Decimal

        price = self.plan.unit_price * Decimal(self.duration_months)
        return price * (Decimal("1") - self.discount_rate)

    def __str__(self) -> str:
        return f"{self.plan.name} × {self.duration_months}mo ({self.discount_rate})"


class Subscription(models.Model):
    """A business's SaaS subscription (doc §39–40, §53–56).

    Created as a 3-day TRIAL at signup (§55) and flipped to ACTIVE when a
    purpose=subscription Payment confirms (§41). Idempotent on (business, payment)
    via the activate service.
    """

    class Status(models.TextChoices):
        TRIAL = "trial", "trial"
        ACTIVE = "active", "active"
        EXPIRED = "expired", "expired"
        CANCELLED = "cancelled", "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL)
    offer = models.ForeignKey(SubscriptionOffer, null=True, blank=True, on_delete=models.SET_NULL)
    payment = models.ForeignKey(
        Payment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subscriptions",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TRIAL)
    started_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["business", "status"])]

    @property
    def is_current(self) -> bool:
        from django.utils import timezone

        if self.status == Subscription.Status.CANCELLED:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return self.status in (Subscription.Status.TRIAL, Subscription.Status.ACTIVE)

    @property
    def is_trial(self) -> bool:
        return self.status == Subscription.Status.TRIAL

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        if self.expires_at is None:
            return False
        return self.expires_at <= timezone.now()

    def __str__(self) -> str:
        return f"{self.business.name} {self.status}"
