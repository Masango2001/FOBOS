"""Demo adapters — local stand-ins so the full chain runs without Backend Dev B's
real BitLibera/Blink adapters. Registered only when FOBOS_USE_DEMO_ADAPTERS=true.
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from .adapters import AdapterInvoice, AdapterStatus, PaymentRailAdapter


class DemoBitLiberaOfframpAdapter(PaymentRailAdapter):
    rail = "bitlibera_offramp"

    def create_invoice(
        self, *, amount: Decimal, currency: str, business, order_id: str
    ) -> AdapterInvoice:
        return AdapterInvoice(
            order_id=order_id,
            payment_request=f"lnbc1demo-{order_id[:24]}",
            amount_bif=amount,
        )

    def get_status(self, order_id: str) -> AdapterStatus:
        return AdapterStatus(status="confirmed", confirmed_at=timezone.now())


class DemoBlinkDirectAdapter(PaymentRailAdapter):
    rail = "blink_direct"

    def create_invoice(
        self, *, amount: Decimal, currency: str, business, order_id: str
    ) -> AdapterInvoice:
        return AdapterInvoice(
            order_id=order_id,
            payment_request=f"lnbc1demo-{order_id[:24]}",
            amount_sats=int(amount),
        )

    def get_status(self, order_id: str) -> AdapterStatus:
        return AdapterStatus(status="confirmed", confirmed_at=timezone.now())
