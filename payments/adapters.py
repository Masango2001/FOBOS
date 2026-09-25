"""PaymentRailAdapter interface + registry (Tech Spec §5, PRD §11)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from accounts.models import Business


class AdapterNotInstalled(Exception):
    """No payment adapter is registered for the requested rail."""

    def __init__(self, rail: str) -> None:
        super().__init__(f"No PaymentRailAdapter registered for rail '{rail}'")
        self.rail = rail


@dataclass(frozen=True)
class AdapterInvoice:
    """Result of create_invoice — shaped like the Tech Spec §5 contract."""

    order_id: str
    payment_request: str
    amount_sats: int | None = None
    amount_bif: Decimal | None = None
    settlement_currency: str | None = None
    settlement_amount: Decimal | None = None
    exchange_rate: Decimal | None = None
    rate_source: str = ""
    rate_timestamp: object | None = None


@dataclass(frozen=True)
class AdapterStatus:
    status: str
    confirmed_at: object | None = None
    amount_bif: Decimal | None = None
    amount_sats: int | None = None


@dataclass(frozen=True)
class AdapterOtpSent:
    """Result of request_otp — the customer receives an SMS OTP (Lumicash relay)."""

    status: str = "otp_sent"
    demo_otp: str | None = None


class OnrampOtpError(Exception):
    """OTP mismatch / expired — HTTP 400."""

    def __init__(self, message: str, code: str = "invalid_otp") -> None:
        super().__init__(message)
        self.code = code


class PaymentRailAdapter(ABC):
    """Common interface so the event handler never branches on rail type (§5)."""

    rail: str

    @abstractmethod
    def create_invoice(
        self,
        *,
        amount: Decimal,
        currency: str,
        business: Business,
        order_id: str,
    ) -> AdapterInvoice: ...

    @abstractmethod
    def get_status(self, order_id: str) -> AdapterStatus: ...


class OnrampAdapter(ABC):
    """Lumicash-OTP adapter; live requests are relayed through BitLibera."""

    rail: str

    @abstractmethod
    def request_otp(self, *, customer_phone: str, amount: Decimal, business=None, order_id="") -> AdapterOtpSent: ...

    @abstractmethod
    def confirm_otp(self, *, customer_phone: str, amount: Decimal, otp: str, business=None, order_id="") -> None: ...


_REGISTRY: dict[str, PaymentRailAdapter] = {}
_ONRAMP_REGISTRY: dict[str, OnrampAdapter] = {}


def register_adapter(adapter: PaymentRailAdapter) -> None:
    _REGISTRY[adapter.rail] = adapter


def get_adapter(rail: str) -> PaymentRailAdapter:
    adapter = _REGISTRY.get(rail)
    if adapter is None:
        raise AdapterNotInstalled(rail)
    return adapter


def register_onramp_adapter(adapter: OnrampAdapter) -> None:
    _ONRAMP_REGISTRY[adapter.rail] = adapter


def get_onramp_adapter(rail: str) -> OnrampAdapter:
    adapter = _ONRAMP_REGISTRY.get(rail)
    if adapter is None:
        raise AdapterNotInstalled(rail)
    return adapter


def rails_by_settlement_preference(preference: str) -> str:
    """QR and subscription invoices are issued by Blink for either preference."""
    return "blink_direct"
