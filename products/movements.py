"""Stock movement service — the ONLY path that mutates Product.stock_qty.

LOT 1 business rules:
  - Rules 1 & 3: stock never changes without an associated StockMovement row
    created in the same DB transaction.
  - Rule 2: a movement that would make stock negative is rejected (409).
  - Rule 6: an "adjustment" movement requires a non-empty reason.
  - Rule 4 (idempotency) is enforced at the checkout handler (sales/services.py),
    keyed on order_id / financial_event_id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

if TYPE_CHECKING:
    from .models import Product, StockMovement
else:
    from .models import StockMovement


class NegativeStockError(Exception):
    """Raised when a movement would drive stock below zero."""

    def __init__(self, product_id, current_stock: int, qty_delta: int):
        self.product_id = product_id
        self.current_stock = current_stock
        self.qty_delta = qty_delta


class AdjustmentReasonRequiredError(Exception):
    """Raised when an adjustment movement has an empty reason."""


def record_stock_movement(
    *,
    product: Product,
    movement_type: str,
    qty_delta: int,
    qty_after: int,
    reason: str | None = None,
    reference: str | None = None,
) -> StockMovement:
    """Append one immutable movement row (no stock mutation).

    Used for the initial stock at product creation (the product already holds
    its final stock value) and internally by `apply_stock_movement`.
    """
    return StockMovement.objects.create(
        business=product.business,
        product=product,
        type=movement_type,
        qty_delta=int(qty_delta),
        qty_after=int(qty_after),
        reference=reference or None,
        reason=reason or None,
    )


def apply_stock_movement(
    *,
    product: Product,
    movement_type: str,
    qty_delta: int,
    reason: str | None = None,
    reference: str | None = None,
) -> StockMovement:
    """Atomic: update stock_qty + append the movement row.

    Caller is responsible for opening the surrounding transaction (checkout
    handler opens one; a standalone call opens its own). `product` is expected
    to already be locked with select_for_update when called from the sale flow.
    """
    if movement_type == StockMovement.MovementType.ADJUSTMENT and not (reason or "").strip():
        raise AdjustmentReasonRequiredError()

    new_qty = int(product.stock_qty) + int(qty_delta)
    if new_qty < 0:
        raise NegativeStockError(product.id, int(product.stock_qty), int(qty_delta))

    with transaction.atomic():
        product.stock_qty = new_qty
        product.save(update_fields=["stock_qty"])
        return record_stock_movement(
            product=product,
            movement_type=movement_type,
            qty_delta=int(qty_delta),
            qty_after=new_qty,
            reason=reason,
            reference=reference,
        )
