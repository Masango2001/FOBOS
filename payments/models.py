"""Payment model (Tech Spec §2). Field names are contract — never rename."""

import uuid

from django.db import models

from accounts.models import Business
from ledger.models import Currency, FinancialEvent


class Payment(models.Model):
    class Rail(models.TextChoices):
        BITLIBERA_OFFRAMP = "bitlibera_offramp", "BitLibera off-ramp"
        BITLIBERA_ONRAMP = "bitlibera_onramp", "BitLibera on-ramp"
        BLINK_DIRECT = "blink_direct", "Blink direct"
        CASH = "cash", "Cash"

    class Status(models.TextChoices):
        """Internal FOBOS states (doc §24) — distinct from provider statuses.

        Canonical API values exposed to clients: created|pending|paid|failed|
        expired|cancelled. Provider states (e.g. Blink PENDING/PAID/EXPIRED)
        are translated into these by the views/polling layer.
        """

        CREATED = "created", "created"
        PENDING = "pending", "pending"
        PAID = "paid", "paid"
        FAILED = "failed", "failed"
        EXPIRED = "expired", "expired"
        CANCELLED = "cancelled", "cancelled"

    class Purpose(models.TextChoices):
        CHECKOUT = "checkout", "Cart checkout"
        SUBSCRIPTION = "subscription", "SaaS subscription"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="payments")
    financial_event = models.ForeignKey(
        FinancialEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payments",
    )
    rail = models.CharField(max_length=32, choices=Rail.choices)
    order_id = models.CharField(
        max_length=64, unique=True, help_text="Unique checkout reference and idempotency key."
    )
    payment_request = models.TextField(blank=True, default="")
    amount_sats = models.BigIntegerField(null=True, blank=True)
    amount_bif = models.BigIntegerField(null=True, blank=True)
    amount_tendered = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    lumicash_phone = models.CharField(max_length=30, blank=True, default="")
    lines = models.JSONField(
        default=list,
        blank=True,
        help_text="Frozen cart snapshots [{product_id, quantity, unit_price, unit_cost}].",
    )
    currency = models.CharField(max_length=3, choices=Currency, default=Currency.BIF)
    settlement_currency = models.CharField(
        max_length=3,
        choices=Currency,
        default=Currency.BIF,
        help_text="Currency FOBOS expects to receive (doc §46).",
    )
    settlement_amount = models.DecimalField(
        max_digits=24,
        decimal_places=8,
        null=True,
        blank=True,
        help_text="Quoted amount in settlement_currency when the invoice was created.",
    )
    exchange_rate = models.DecimalField(
        max_digits=24,
        decimal_places=12,
        null=True,
        blank=True,
        help_text="Settlement currency units per one unit of the checkout currency.",
    )
    rate_source = models.CharField(max_length=64, blank=True, default="")
    rate_timestamp = models.DateTimeField(null=True, blank=True)
    purpose = models.CharField(
        max_length=16,
        choices=Purpose.choices,
        default=Purpose.CHECKOUT,
        help_text="What the Payment pays for: checkout or subscription (doc §41).",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["business", "status"])]

    @property
    def total_amount(self):
        from decimal import Decimal

        if self.currency == "BIF" and self.amount_bif is not None:
            return Decimal(self.amount_bif)
        if self.amount_sats is not None:
            return Decimal(self.amount_sats)
        return Decimal("0")

    def __str__(self) -> str:
        return f"Payment {self.order_id} ({self.status})"
