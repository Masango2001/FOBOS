"""Sales models (Tech Spec §2). Field names are contract — never rename."""

from decimal import Decimal

import uuid as _uuid

from django.db import models

from accounts.models import Business, User
from ledger.models import Currency, FinancialEvent
from products.models import Product


class Sale(models.Model):
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="sales")
    financial_event = models.OneToOneField(
        FinancialEvent,
        on_delete=models.PROTECT,
        related_name="sale",
        help_text="One sale per confirmed event — DB-level idempotency guard.",
    )
    cashier = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales",
    )
    total_amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Currency, default=Currency.BIF)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Sale #{self.pk} {self.total_amount} {self.currency}"

    @property
    def lines(self):
        return self.sale_lines.all()


class SaleLine(models.Model):
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="sale_lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sale_lines")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=20, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.quantity}x {self.product.name}"


class Receipt(models.Model):
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    sale = models.OneToOneField(Sale, on_delete=models.CASCADE, related_name="receipt")
    content = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Receipt for {self.sale}"


def line_total(line: SaleLine) -> Decimal:
    return Decimal(str(line.quantity)) * line.unit_price
