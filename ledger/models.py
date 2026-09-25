"""Ledger models — the financial source of truth (Tech Spec §2, PRD §13/§29)."""

import uuid as _uuid

from django.db import models
from django.utils import timezone

from accounts.models import Business


class Currency(models.TextChoices):
    """Single shared currency choice set (BIF reference currency, §2)."""

    BIF = "BIF", "Burundian Franc"
    USD = "USD", "US Dollar"
    SAT = "SAT", "Sats"


CURRENCIES = Currency.choices


class FinancialEvent(models.Model):
    """A normalized event that changes the financial state of a business.

    Backend Dev B hands us a confirmed event through this model — our event
    handler must never branch on which payment rail produced it.
    """

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)

    class EventType(models.TextChoices):
        PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED", "Payment confirmed"
        PAYMENT_PENDING = "PAYMENT_PENDING", "Payment pending"

    class Source(models.TextChoices):
        BITLIBERA_OFFRAMP = "bitlibera_offramp", "BitLibera off-ramp"
        BITLIBERA_ONRAMP = "bitlibera_onramp", "BitLibera on-ramp"
        BLINK_DIRECT = "blink_direct", "Blink direct"

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        CONFIRMED = "confirmed", "confirmed"
        FAILED = "failed", "failed"

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="financial_events"
    )
    type = models.CharField(max_length=32, choices=EventType.choices)
    amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, choices=Currency, default=Currency.BIF)
    timestamp = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=32, choices=Source.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    actor = models.CharField(max_length=150, blank=True, default="")
    reference = models.CharField(max_length=150, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["business", "timestamp"]),
            models.Index(fields=["business", "type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.type} {self.amount} {self.currency} ({self.status})"


class LedgerEntry(models.Model):
    """A single credit/debit movement. Traceable back to its FinancialEvent."""

    class MovementType(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="ledger_entries")
    financial_event = models.ForeignKey(
        FinancialEvent,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    type = models.CharField(max_length=8, choices=MovementType.choices)
    account = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Currency, default=Currency.BIF)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "account", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.type} {self.account} {self.amount} {self.currency}"
