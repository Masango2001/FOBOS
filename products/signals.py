"""Product signals: barcode image sync + LOT 1 initial-stock movement.

- `_sync_barcode_image` persists the Code128 PNG whenever the barcode value
  changes (idempotent on rendered bytes, no recursion).
- `_record_initial_stock` appends the "restock" movement for the stock a
  product is created with, so `/inventory` always equals sum(qty_delta)
  (LOT 1 rule 5) no matter how the product entered the system.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Product, StockMovement


@receiver(post_save, sender=Product, dispatch_uid="fobos_sync_product_barcode_image")
def _sync_barcode_image(instance, **kwargs) -> None:
    from .services import sync_barcode_image

    sync_barcode_image(instance)


@receiver(post_save, sender=Product, dispatch_uid="fobos_record_initial_stock")
def _record_initial_stock(instance, created: bool, **kwargs) -> None:
    if not created:
        return
    if int(instance.stock_qty) <= 0:
        return
    from .movements import record_stock_movement

    record_stock_movement(
        product=instance,
        movement_type=StockMovement.MovementType.RESTOCK,
        qty_delta=int(instance.stock_qty),
        qty_after=int(instance.stock_qty),
        reason="stock initial",
    )
