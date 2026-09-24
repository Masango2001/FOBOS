"""Checkout + payment confirmation services (Tech Spec §3 steps 1–2).

- `create_checkout_payment` builds a pending Payment for a cart and asks the
  adapter (interface only — real adapters belong to Backend Dev B) for an invoice.
- `confirm_payment` is THE integration point Backend Dev B calls once a rail
  confirms an order. It is idempotent on `Payment.order_id`: a duplicate call
  returns the existing FinancialEvent and never creates a second one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from accounts.models import Business, User
from ledger.models import CURRENCIES, FinancialEvent

from .adapters import get_adapter, rails_by_settlement_preference
from .models import Payment


class CheckoutError(Exception):
    """Validation failure at checkout (HTTP 400)."""

    def __init__(self, message: str, code: str = "checkout_error") -> None:
        super().__init__(message)
        self.code = code


class InsufficientStock(CheckoutError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="insufficient_stock")


def create_checkout_payment(
    *,
    user: User,
    lines: list[dict[str, Any]] | None = None,
    amount: Decimal | None = None,
    currency: str = "BIF",
) -> Payment:
    """POST /cart/checkout — Tech Spec §3 step 1."""
    business = user.business
    if business is None:
        raise CheckoutError("User has no business.", code="no_business")
    if currency not in dict(CURRENCIES):
        raise CheckoutError(f"Unsupported currency '{currency}'.", code="bad_currency")

    snapshots, total = _resolve_cart(business, lines=lines, amount=amount)
    rail = rails_by_settlement_preference(business.settlement_preference)
    adapter = get_adapter(rail)  # raises AdapterNotInstalled if missing

    order_id = uuid.uuid4().hex
    invoice = adapter.create_invoice(
        amount=total, currency=currency, business=business, order_id=order_id
    )

    payment = Payment.objects.create(
        business=business,
        rail=rail,
        order_id=order_id,
        payment_request=invoice.payment_request,
        lines=snapshots,
        currency=currency,
        amount_bif=(
            int(total)
            if currency == "BIF"
            else (int(invoice.amount_bif) if invoice.amount_bif is not None else None)
        ),
        amount_sats=invoice.amount_sats,
        status=Payment.Status.PENDING,
    )
    return payment


def _resolve_cart(
    business: Business,
    *,
    lines: list[dict[str, Any]] | None,
    amount: Decimal | None,
) -> tuple[list[dict[str, Any]], Decimal]:
    if lines and amount is not None:
        raise CheckoutError("Provide either 'lines' or 'amount', not both.")
    if not lines and amount is None:
        raise CheckoutError("Provide 'lines' or 'amount'.")
    if amount is not None:
        if amount <= 0:
            raise CheckoutError("'amount' must be positive.")
        return [], amount

    from products.models import Product

    snapshots: list[dict[str, Any]] = []
    total = Decimal("0")
    for raw in lines or []:
        try:
            quantity = int(raw["qty"])
        except (KeyError, TypeError, ValueError):
            try:
                quantity = int(raw["quantity"])
            except (KeyError, TypeError, ValueError):
                raise CheckoutError("Each line needs a positive integer 'qty'.") from None
        if quantity <= 0:
            raise CheckoutError("Line quantity must be positive.")
        try:
            product_id = int(raw["product_id"])
        except (KeyError, TypeError, ValueError):
            raise CheckoutError("Each line needs a 'product_id'.") from None

        product = Product.objects.filter(business=business, pk=product_id).first()
        if product is None:
            raise CheckoutError(f"Product {product_id} not found.", code="unknown_product")
        if product.stock_qty < quantity:
            raise InsufficientStock(
                f"Insufficient stock for {product.name}: "
                f"requested {quantity}, available {product.stock_qty}"
            )
        snapshots.append(
            {
                "product_id": product.id,
                "quantity": quantity,
                "unit_price": str(product.unit_price),
                "unit_cost": str(product.unit_cost),
            }
        )
        total += product.unit_price * quantity
    return snapshots, total


def confirm_payment(
    *,
    order_id: str,
    amount_bif: int | None = None,
    amount_sats: int | None = None,
    actor: str = "",
    metadata: dict[str, Any] | None = None,
    confirmed_at=None,
) -> FinancialEvent:
    """Idempotent confirmation — duplicate order_id calls never duplicate records.

    This is the handoff from Backend Dev B's adapters: call it once a rail
    reports an order as paid. Safe to retry (select_for_update + order_id guard).
    """
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(order_id=order_id)
        if payment.financial_event_id is not None:
            existing = payment.financial_event
            assert existing is not None
            return existing

        confirmed_at = confirmed_at or timezone.now()
        event = FinancialEvent.objects.create(
            business=payment.business,
            type=FinancialEvent.EventType.PAYMENT_CONFIRMED,
            amount=Decimal(amount_bif if amount_bif is not None else 0),
            currency=payment.currency,
            timestamp=confirmed_at,
            source=payment.rail,
            status=FinancialEvent.Status.CONFIRMED,
            actor=actor,
            reference=order_id,
            metadata=metadata or {},
        )
        # Synchronous signal runs handle_financial_event inside this transaction.
        payment.financial_event = event
        payment.status = Payment.Status.CONFIRMED
        payment.confirmed_at = confirmed_at
        if amount_bif is not None:
            payment.amount_bif = amount_bif
        if amount_sats is not None:
            payment.amount_sats = amount_sats
        payment.save(
            update_fields=[
                "financial_event",
                "status",
                "confirmed_at",
                "amount_bif",
                "amount_sats",
            ]
        )
        return event
