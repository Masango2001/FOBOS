"""BitLibera higher-level services (doc §17).

`BitLiberaService` maps operations FOBOS cares about (on-ramp OTP, on-ramp
execute, off-ramp invoice, order status) onto the REST endpoints, so the
`payments/` layer never imports `endpoints.py` or sees the raw payloads.
Doc §14/§17 payloads are the contractual shapes; the order-status translation
returns the canonical FOBOS axis (doc §24).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .client import BitLiberaClient
from .endpoints import (
    OFFRAMP_CREATE_INVOICE,
    ONRAMP_EXECUTE,
    ONRAMP_REQUEST_OTP,
    ORDER_STATUS,
)

ORDER_STATUS_MAP = {
    "PENDING_PAYMENT": "pending",
    "PENDING": "pending",
    "PAID": "paid",
    "COMPLETED": "paid",
    "SETTLED": "paid",
    "EXPIRED": "expired",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
}


def translate_order_status(status: str | None) -> str:
    """Map a BitLibera order status to the canonical FOBOS axis (doc §24).

    Unknown statuses pass through lowercased so new gateway states never crash
    the translation.
    """
    key = (status or "").upper()
    return ORDER_STATUS_MAP.get(key, (status or "").lower())


class BitLiberaService:
    """Operations FOBOS needs from the BitLibera gateway.

    The `recipient_phone` here is the Lumicash destination of an off-ramp, and
    the `phone` of an on-ramp OTP debut — never the company global coordinates
    of doc §47 (those live in the merchant configuration).
    """

    def __init__(self, client: BitLiberaClient | None = None) -> None:
        self.client = client or BitLiberaClient()

    def request_onramp_otp(self, phone: str, amount_bif: Decimal | int | float) -> dict[str, Any]:
        """Ask BitLibera to SMS a Lumicash OTP (doc §14, §19)."""
        return self.client.post(
            ONRAMP_REQUEST_OTP,
            {"phone": phone, "amount": int(amount_bif)},
        )

    def execute_onramp(
        self,
        phone: str,
        amount_bif: Decimal | int | float,
        otp: str,
        order_id: str,
    ) -> dict[str, Any]:
        """Execute the on-ramp: debit Lumicash and credit the Lightning side (doc §14)."""
        return self.client.post(
            ONRAMP_EXECUTE,
            {
                "phone": phone,
                "amount": int(amount_bif),
                "otp": otp,
                "order_id": order_id,
            },
        )

    def create_offramp_invoice(
        self,
        recipient_phone: str,
        amount_bif: Decimal | int | float,
        order_id: str,
    ) -> dict[str, Any]:
        """Create a BOLT11 invoice BitLibera pays into Lumicash (doc §14, §20).

        The returned body contains `payment_request` + `payment_hash` — the
        Lightning destination the sats must be sent to, and the `amount_sats`.
        """
        return self.client.post(
            OFFRAMP_CREATE_INVOICE,
            {
                "recipient_phone": recipient_phone,
                "amount_bif": int(amount_bif),
                "order_id": order_id,
            },
        )

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Poll the state of an order (doc §14, §25 — no BitLibera webhook)."""
        return self.client.get(ORDER_STATUS.format(order_id=order_id))

    def order_status(self, order_id: str) -> str:
        """Poll and translate the order status to the canonical FOBOS axis."""
        return translate_order_status(self.get_order_status(order_id).get("status"))
