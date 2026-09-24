"""The atomic checkout→ledger event handler (Tech Spec §3 step 3, PRD §27).

Single DB transaction: Sale + SaleLine + LedgerEntry (revenue + COGS) +
stock decrement — all succeed or all fail together. Idempotent on
FinancialEvent (guarded at the Sale level, one Sale per confirmed event).
"""

import logging
import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from automation.services import run_automation_for_event
from ledger.financial import cogs
from ledger.models import FinancialEvent, LedgerEntry

from .models import Receipt, Sale, SaleLine

logger = logging.getLogger(__name__)


class InsufficientStockError(Exception):
    """Raised when a product cannot cover the requested quantity — rolls everything back."""


def handle_financial_event(event: FinancialEvent) -> Sale:
    """Create the business state for a confirmed payment — atomic and idempotent."""
    existing = Sale.objects.filter(financial_event=event).first()
    if existing is not None:
        return existing

    from payments.models import Payment  # local import: payments → sales boundary

    with transaction.atomic():
        sale = Sale.objects.select_for_update().filter(financial_event=event).first()
        if sale is not None:
            return sale

        payment = (
            Payment.objects.select_for_update()
            .filter(business=event.business)
            .filter(_payment_backing_q(event))
            .first()
        )
        if payment is None:
            raise ValueError(f"No payment backing FinancialEvent {event.pk}")

        # Duplicate confirmation must never create duplicate financial records.
        if payment.financial_event_id is not None and payment.financial_event_id != event.pk:
            existing_for_payment = Sale.objects.filter(
                financial_event_id=payment.financial_event_id
            ).first()
            if existing_for_payment is not None:
                return existing_for_payment
            raise ValueError(f"Payment {payment.order_id} already confirmed elsewhere")

        sale = Sale.objects.create(
            business=event.business,
            financial_event=event,
            cashier=_cashier_for(event),
            total_amount=payment.total_amount,
            currency=payment.currency,
        )

        total_cogs = Decimal("0")
        for snap in payment.lines or []:
            product = _locked_product(event, snap)
            quantity = int(snap["quantity"])
            if product.stock_qty < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock for product {product.name}: "
                    f"requested {quantity}, available {product.stock_qty}"
                )

            # LOT 1 rule 3: stock never changes without an associated movement,
            # in the same transaction as the decrement + sale line + ledger.
            from products.movements import apply_stock_movement
            from products.models import StockMovement

            apply_stock_movement(
                product=product,
                movement_type=StockMovement.MovementType.SALE,
                qty_delta=-quantity,
                reason="vente",
                reference=payment.order_id,
            )

            SaleLine.objects.create(
                sale=sale,
                product=product,
                quantity=quantity,
                unit_price=Decimal(str(snap["unit_price"])),
                unit_cost=Decimal(str(snap["unit_cost"])),
            )
            total_cogs += cogs(
                type("_Line", (), {"quantity": quantity, "unit_cost": snap["unit_cost"]})()
            )

        LedgerEntry.objects.create(
            business=event.business,
            financial_event=event,
            type=LedgerEntry.MovementType.CREDIT,
            account="REVENUE",
            amount=sale.total_amount,
            currency=sale.currency,
        )
        LedgerEntry.objects.create(
            business=event.business,
            financial_event=event,
            type=LedgerEntry.MovementType.DEBIT,
            account="COGS",
            amount=total_cogs,
            currency=sale.currency,
        )

        Receipt.objects.create(
            sale=sale,
            content={
                "sale_id": str(sale.id),
                "order_id": payment.order_id,
                "total_amount": str(sale.total_amount),
                "currency": sale.currency,
                "lines": [
                    {
                        "product_id": str(line.product_id),
                        "quantity": line.quantity,
                        "unit_price": str(line.unit_price),
                    }
                    for line in sale.sale_lines.all()
                ],
                "created_at": timezone.now().isoformat(),
            },
        )

    # Automation evaluates the new state after the sale transaction (§3 step 4).
    # Runs inside the caller's transaction when one is open; a failing rule must
    # never undo a recorded, confirmed sale.
    try:
        run_automation_for_event(event)
    except Exception:  # pragma: no cover - guardrail, the sale is already committed
        logger.exception("Automation failed for financial event %s", event.pk)

    return sale


def _payment_backing_q(event: FinancialEvent):
    from django.db.models import Q

    if event.reference:
        return Q(financial_event=event) | Q(order_id=event.reference)
    return Q(financial_event=event)


def _locked_product(event: FinancialEvent, snap: dict[str, Any]):
    from products.models import Product

    try:
        product_id = uuid.UUID(str(snap["product_id"]))
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"Invalid product reference {snap.get('product_id')!r}") from None
    product = (
        Product.objects.select_for_update().filter(business=event.business, pk=product_id).first()
    )
    if product is None:
        raise ValueError(f"Product {product_id} not found for this business")
    return product


def _cashier_for(event: FinancialEvent):
    from accounts.models import User

    actor = event.actor
    if actor:
        return User.objects.filter(business=event.business, email__iexact=actor).first() or None
    return None
