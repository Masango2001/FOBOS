"""Signals — confirmed FinancialEvents drive the atomic checkout→ledger chain (§3 step 3)."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FinancialEvent


@receiver(post_save, sender=FinancialEvent, dispatch_uid="fobos_handle_confirmed_event")
def handle_confirmed_financial_event(
    sender, instance: FinancialEvent, created: bool, **kwargs: object
) -> None:
    if not created:
        return
    if instance.type != FinancialEvent.EventType.PAYMENT_CONFIRMED:
        return
    if instance.status != FinancialEvent.Status.CONFIRMED:
        return
    # Imported lazily to avoid a module-level cycle (sales depends on ledger).
    from sales.services import handle_financial_event

    handle_financial_event(instance)
