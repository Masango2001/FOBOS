"""Demo adapters — local stand-ins so the full chain runs without Backend Dev B's
real BitLibera/Blink adapters. Registered only when FOBOS_USE_DEMO_ADAPTERS=true.
"""

from __future__ import annotations

import secrets
from decimal import Decimal

from django.utils import timezone

from .adapters import (
    AdapterInvoice,
    AdapterOtpSent,
    AdapterStatus,
    OnrampAdapter,
    OnrampOtpError,
    PaymentRailAdapter,
)


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


class DemoBitLiberaOnrampAdapter(OnrampAdapter):
    """Local Lumicash-OTP stand-in: OTP is stored in memory and logged.

    Real BitLibera sends the OTP by SMS (`onramp/request-otp`) and validates it
    via `onramp/execute` — Backend Dev B. `demo_otp` is returned by the demo
    adapter ONLY so the MVP front can complete a payment without SMS access.
    """

    rail = "bitlibera_onramp"

    def __init__(self) -> None:
        self._otps: dict[tuple[str, str], str] = {}

    def request_otp(self, *, customer_phone: str, amount: Decimal, business=None, order_id="") -> AdapterOtpSent:
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._otps[(customer_phone, str(amount))] = code
        return AdapterOtpSent(status="otp_sent", demo_otp=code)

    def confirm_otp(self, *, customer_phone: str, amount: Decimal, otp: str, business=None, order_id="") -> None:
        stored = self._otps.pop((customer_phone, str(amount)), None)
        if stored is None or stored != otp:
            raise OnrampOtpError("Invalid or expired OTP.")


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
