"""Product/inventory models, plus the four MVP-skipped tables (Tech Spec §2).

The tracked entities (`Customer`, `Supplier`, `Invoice`, `Expense`) must keep
their tables in the schema for Phase 2 but carry **no logic** in the MVP — they
exist so future migrations land on a stable schema.
"""

from decimal import Decimal

import uuid as _uuid

from django.db import models

from accounts.models import Business


class Product(models.Model):
    """A sellable item. Field names are the Tech Spec §2 contract — never rename."""

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=200)
    barcode = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text="Manufacturer barcode, or FOBOS-generated: base64(name|price|id).",
    )
    unit_cost = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=20, decimal_places=2)
    stock_qty = models.PositiveIntegerField(default=0)
    stock_threshold = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "barcode"],
                name="uniq_business_barcode",
                condition=models.Q(barcode__isnull=False),
            )
        ]

    @property
    def inventory_value(self) -> Decimal:
        return self.stock_qty * self.unit_cost

    @property
    def low_stock(self) -> bool:
        return self.stock_threshold > 0 and self.stock_qty < self.stock_threshold

    def __str__(self) -> str:
        return self.name


class Customer(models.Model):
    """MVP-skip table: exists in schema, no logic yet (Tech Spec §2)."""

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Supplier(models.Model):
    """MVP-skip table: exists in schema, no logic yet (Tech Spec §2)."""

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="suppliers")
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Invoice(models.Model):
    """MVP-skip table: exists in schema, no logic yet (Tech Spec §2)."""

    class Kind(models.TextChoices):
        CUSTOMER = "customer", "Customer invoice"
        SUPPLIER = "supplier", "Supplier invoice"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        RECONCILED = "reconciled", "Reconciled"
        CANCELLED = "cancelled", "Cancelled"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="invoices")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CUSTOMER)
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    supplier = models.ForeignKey(
        Supplier,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3, default="BIF")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Invoice #{self.pk}"


class Expense(models.Model):
    """MVP-skip table: exists in schema, no logic yet (Tech Spec §2)."""

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="expenses")
    description = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3, default="BIF")
    occurred_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.description or f"Expense #{self.pk}"
