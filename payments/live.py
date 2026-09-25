"""HTTP adapters for BitLibera and Blink. Credentials and endpoints are server-only."""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.utils import timezone

from .adapters import (
    AdapterInvoice,
    AdapterOtpSent,
    AdapterStatus,
    OnrampAdapter,
    OnrampOtpError,
    PaymentRailAdapter,
)


class ProviderError(RuntimeError):
    """A payment provider returned an unusable response."""


def _request_json(url: str, *, payload=None, headers=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=body, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise ProviderError("Payment provider request failed.") from exc
    if not isinstance(result, dict):
        raise ProviderError("Payment provider returned an invalid response.")
    return result


def _bitlibera_headers(business):
    key = business.bitlibera_api_key or os.getenv("BITLIBERA_API_KEY", "")
    if not key:
        raise ProviderError("BitLibera credentials are not configured.")
    return {"Content-Type": "application/json", "x-api-key": key}


def _provider_data(result):
    if result.get("success") is False or result.get("error"):
        raise ProviderError("Payment provider rejected the request.")
    return result.get("data", result.get("result", result))


def _bif_amount(amount: Decimal) -> int:
    """BitLibera's documented amount_bif field is a whole-number BIF amount."""
    amount = Decimal(amount)
    if amount != amount.to_integral_value():
        raise ProviderError("BitLibera accepts whole-number BIF amounts only.")
    return int(amount)


class BitLiberaOfframpAdapter(PaymentRailAdapter):
    rail = "bitlibera_offramp"

    def create_invoice(self, *, amount: Decimal, currency: str, business, order_id: str):
        if currency != "BIF":
            raise ProviderError("BitLibera off-ramp checkout currently supports BIF only.")
        base = os.getenv("BITLIBERA_API_URL", "https://exchanger.bitlibera.com/api/v1").rstrip("/")
        data = _provider_data(
            _request_json(
                f"{base}/offramp/create-invoice",
                payload={
                    "recipient_phone": business.lumicash_number,
                    "amount_bif": _bif_amount(amount),
                    "order_id": order_id,
                },
                headers=_bitlibera_headers(business),
            )
        )
        invoice = data.get("payment_request") or data.get("invoice") or data.get("bolt11")
        if not invoice:
            raise ProviderError("BitLibera did not return a Lightning invoice.")
        sats = data.get("amount_sats") or data.get("sats")
        return AdapterInvoice(order_id, invoice, int(sats) if sats is not None else None, amount)

    def get_status(self, order_id: str):
        base = os.getenv("BITLIBERA_API_URL", "https://exchanger.bitlibera.com/api/v1").rstrip("/")
        # Payment stores the business-scoped API key; resolve only this order's tenant.
        from .models import Payment

        payment = Payment.objects.select_related("business").get(order_id=order_id)
        data = _provider_data(
            _request_json(
                f"{base}/orders/{quote(order_id, safe='')}",
                headers=_bitlibera_headers(payment.business),
            )
        )
        raw = str(data.get("status", "pending")).lower()
        state = (
            "confirmed" if raw in {"confirmed", "paid", "success", "completed", "settled"} else raw
        )
        confirmed_at = data.get("confirmed_at")
        if isinstance(confirmed_at, str):
            try:
                confirmed_at = datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
            except ValueError:
                confirmed_at = timezone.now() if state == "confirmed" else None
        return AdapterStatus(state, confirmed_at=confirmed_at)


class BitLiberaOnrampAdapter(OnrampAdapter):
    rail = "bitlibera_onramp"

    def request_otp(self, *, customer_phone: str, amount: Decimal, business=None, order_id=""):
        base = os.getenv("BITLIBERA_API_URL", "https://exchanger.bitlibera.com/api/v1").rstrip("/")
        data = _provider_data(
            _request_json(
                f"{base}/onramp/request-otp",
                payload={
                    "phone": customer_phone,
                    "amount": _bif_amount(amount),
                    "order_id": order_id,
                },
                headers=_bitlibera_headers(business),
            )
        )
        return AdapterOtpSent(status=str(data.get("status", "otp_sent")))

    def confirm_otp(
        self, *, customer_phone: str, amount: Decimal, otp: str, business=None, order_id=""
    ):
        base = os.getenv("BITLIBERA_API_URL", "https://exchanger.bitlibera.com/api/v1").rstrip("/")
        try:
            data = _provider_data(
                _request_json(
                    f"{base}/onramp/confirm-otp",
                    payload={
                        "phone": customer_phone,
                        "amount": _bif_amount(amount),
                        "otp": otp,
                        "order_id": order_id,
                    },
                    headers=_bitlibera_headers(business),
                )
            )
        except ProviderError as exc:
            raise OnrampOtpError("BitLibera could not validate the Lumicash OTP.") from exc
        if data.get("status") and str(data["status"]).lower() in {"failed", "rejected", "error"}:
            raise OnrampOtpError("BitLibera could not validate the Lumicash OTP.")


class BlinkDirectAdapter(PaymentRailAdapter):
    rail = "blink_direct"

    def __init__(self):
        self.endpoint = os.getenv("BLINK_API_URL", "https://api.blink.sv/graphql")

    def _graphql(self, query, variables):
        data = _request_json(
            self.endpoint,
            payload={"query": query, "variables": variables},
            headers={"Content-Type": "application/json"},
        )
        if data.get("errors"):
            raise ProviderError("Blink rejected the GraphQL request.")
        return data.get("data") or {}

    def create_invoice(self, *, amount: Decimal, currency: str, business, order_id: str):
        # Blink does not publish a BIF price in the supplied currency contract.
        # Do not create an invoice with a guessed or stale BIF→sats conversion.
        if currency == "BIF":
            raise ProviderError(
                "Blink settlement for BIF-priced sales needs a documented BIF-to-sats quote. "
                "Choose BIF/Lumicash settlement or price this sale in USD/sats."
            )

        wallet = (
            self._graphql(
                "query AccountDefaultWallet($username: Username!) { accountDefaultWallet(username: $username) { id currency } }",
                {"username": business.blink_username},
            ).get("accountDefaultWallet")
            or {}
        )
        wallet_id = wallet.get("id")
        wallet_currency = str(wallet.get("currency", "")).upper()
        if not wallet_id:
            raise ProviderError("Blink merchant wallet was not found.")

        # A USD wallet receives a USD-denominated invoice. Blink expects cents.
        if wallet_currency == "USD":
            if currency != "USD":
                raise ProviderError("USD Blink wallets currently require USD-priced sales.")
            cents = int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            invoice_result = (
                self._graphql(
                    "mutation CreateUsdInvoice($input: LnUsdInvoiceCreateOnBehalfOfRecipientInput!) { lnUsdInvoiceCreateOnBehalfOfRecipient(input: $input) { invoice { paymentRequest satoshis } } }",
                    {
                        "input": {
                            "recipientWalletId": wallet_id,
                            "amount": cents,
                            "memo": f"FOBOS {order_id}",
                            "expiresIn": "15",
                        }
                    },
                ).get("lnUsdInvoiceCreateOnBehalfOfRecipient")
                or {}
            )
            invoice = invoice_result.get("invoice") or {}
            if not invoice.get("paymentRequest"):
                raise ProviderError("Blink did not return a USD invoice.")
            return AdapterInvoice(
                order_id, invoice["paymentRequest"], int(invoice.get("satoshis") or 0), amount
            )

        if wallet_currency not in {"BTC", "SAT", "SATS"}:
            raise ProviderError(f"Unsupported Blink receiving wallet currency '{wallet_currency}'.")

        if currency in {"SAT", "SATS"}:
            sats = int(amount.to_integral_value(rounding=ROUND_HALF_UP))
        else:
            # Blink's exchange quote supports USD, but not BIF (rejected above).
            quote_currency = "USD" if currency == "USD" else currency
            quote_data = (
                self._graphql(
                    "query RealtimePrice($currency: DisplayCurrency!) { realtimePrice(currency: $currency) { btcSatPrice { base offset } } }",
                    {"currency": quote_currency},
                ).get("realtimePrice")
                or {}
            )
            price = quote_data.get("btcSatPrice") or {}
            if price.get("base") is None or price.get("offset") is None:
                raise ProviderError("Blink could not quote this checkout currency.")
            sats = int(
                (amount * Decimal(str(price["base"])) * (Decimal(10) ** int(price["offset"]))).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        invoice_result = (
            self._graphql(
                "mutation CreateInvoice($input: LnInvoiceCreateOnBehalfOfRecipientInput!) { lnInvoiceCreateOnBehalfOfRecipient(input: $input) { invoice { paymentRequest satoshis } } }",
                {
                    "input": {
                        "recipientWalletId": wallet_id,
                        "amount": str(sats),
                        "memo": f"FOBOS {order_id}",
                        "expiresIn": "15",
                    }
                },
            ).get("lnInvoiceCreateOnBehalfOfRecipient")
            or {}
        )
        invoice = invoice_result.get("invoice") or {}
        if not invoice.get("paymentRequest"):
            raise ProviderError("Blink did not return a Lightning invoice.")
        return AdapterInvoice(
            order_id, invoice["paymentRequest"], int(invoice.get("satoshis", sats)), amount
        )

    def get_status(self, order_id: str):
        from .models import Payment

        payment = Payment.objects.get(order_id=order_id)
        result = (
            self._graphql(
                "query PaymentStatus($input: LnInvoicePaymentStatusInput!) { lnInvoicePaymentStatus(input: $input) { status } }",
                {"input": {"paymentRequest": payment.payment_request}},
            ).get("lnInvoicePaymentStatus")
            or {}
        )
        raw = str(result.get("status", "pending")).lower()
        return AdapterStatus("confirmed" if raw in {"paid", "success", "confirmed"} else raw)
