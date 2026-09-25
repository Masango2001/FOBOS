"""Subscription signals — the canonical §41 handoff.

`Payment.Status.PAID` with `purpose=subscription` → `Subscription` becomes
ACTIVE (100% of features). The signal is thin: it only calls
`subscriptions.services.activate_from_payment`, which is idempotent on the
Payment (a duplicate/webhook-retry confirm never creates a second Subscription
and never re-runs side effects twice).
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from payments.models import Payment


@receiver(post_save, sender=Payment)
def activate_subscription_on_paid(sender, instance, **kwargs):
    if instance.purpose != Payment.Purpose.SUBSCRIPTION:
        return
    if instance.status != Payment.Status.PAID:
        return
    from .services import activate_from_payment

    activate_from_payment(payment=instance)
