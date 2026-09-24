"""Keep the persisted barcode image in sync with the product barcode value."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Product


@receiver(post_save, sender=Product, dispatch_uid="fobos_sync_product_barcode_image")
def _sync_barcode_image(instance, **kwargs) -> None:
    from .services import sync_barcode_image

    sync_barcode_image(instance)
