"""Live payment adapters: Blink invoices and BitLibera Lumicash OTP only."""

from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP

from integrations.bitlibera.client import BitLiberaClient
from integrations.bitlibera.exceptions import BitLiberaAPIError, BitLiberaError, BitLiberaOrderError
from integrations.bitlibera.services import BitLiberaService
from integrations.blink.client import BlinkClient
from integrations.blink.exceptions import BlinkError
from integrations.blink.services import BlinkService
from integrations.yadio import YadioError, get_yadio_rates

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


class BitLiberaOnrampAdapter(OnrampAdapter):
    """BitLibera handles only the customer Lumicash OTP debit flow."""

    rail = "bitlibera_onramp"

    def __init__(self, service: BitLiberaService | None = None):
        self.service = service

    def _service(self) -> BitLiberaService:
        if self.service is None:
            self.service = BitLiberaService(BitLiberaClient())
        return self.service

    @staticmethod
    def _bif_amount(amount: Decimal) -> int:
        amount = Decimal(amount)
        if amount != amount.to_integral_value():
            raise ProviderError("BitLibera Lumicash OTP requires a whole-number BIF amount.")
        return int(amount)

    def request_otp(self, *, customer_phone: str, amount: Decimal, business=None, order_id=""):
        try:
            result = self._service().request_onramp_otp(
                customer_phone, self._bif_amount(amount)
            )
        except BitLiberaError as exc:
            raise ProviderError("BitLibera could not send the Lumicash OTP.") from exc
        status = str(result.get("status") or result.get("otp_status") or "otp_sent").lower()
        if status in {"failed", "rejected", "error"}:
            raise ProviderError("BitLibera rejected the Lumicash OTP request.")
        return AdapterOtpSent(status=status)

    def confirm_otp(
        self, *, customer_phone: str, amount: Decimal, otp: str, business=None, order_id=""
    ) -> None:
        try:
            result = self._service().execute_onramp(
                customer_phone,
                self._bif_amount(amount),
                otp,
                order_id,
            )
        except BitLiberaOrderError as exc:
            raise OnrampOtpError("BitLibera rejected the Lumicash OTP.") from exc
        except BitLiberaAPIError as exc:
            if exc.status_code == 400:
                raise OnrampOtpError("BitLibera rejected the Lumicash OTP.") from exc
            raise ProviderError("BitLibera could not confirm the Lumicash payment.") from exc
        except BitLiberaError as exc:
            raise ProviderError("BitLibera could not confirm the Lumicash payment.") from exc

        status = str(result.get("status") or "").lower()
        if status in {"failed", "rejected", "error"}:
            raise OnrampOtpError("BitLibera rejected the Lumicash OTP.")


class BlinkDirectAdapter(PaymentRailAdapter):
    """Create a USD or BTC-wallet Lightning invoice for a BIF-priced checkout."""

    rail = "blink_direct"

    def __init__(self, blink: BlinkService | None = None):
        self.blink = blink

    def _blink(self) -> BlinkService:
        if self.blink is None:
            client = BlinkClient(
                url=os.getenv("BLINK_API_URL") or "https://api.blink.sv/graphql",
                api_key=os.getenv("BLINK_API_KEY") or None,
            )
            self.blink = BlinkService(client=client)
        return self.blink

    def create_invoice(self, *, amount: Decimal, currency: str, business, order_id: str):
        if currency != "BIF":
            raise ProviderError("QR checkout is priced in BIF; Blink settles to the configured USD or BTC wallet.")

        try:
            blink = self._blink()
            wallet = blink.default_wallet(
                username=business.blink_username or None,
                wallet_currency="",
            )
            wallet_id = wallet.get("id")
            wallet_currency = str(wallet.get("walletCurrency") or wallet.get("currency") or "").upper()
            if not wallet_id:
                raise ProviderError("Blink did not return a receiving wallet for this business.")

            rates = get_yadio_rates()
            if wallet_currency == "USD":
                usd_amount = rates.fiat_amount(amount, source="BIF", target="USD")
                cents = int((usd_amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                if cents < 1:
                    raise ProviderError("The checkout total is below Blink's minimum USD invoice amount.")
                invoice = blink.create_invoice_usd_cents(
                    cents,
                    wallet_id=wallet_id,
                    memo=f"FOBOS {order_id}",
                )
                settlement_currency = "USD"
                settlement_amount = usd_amount
            elif wallet_currency == "BTC":
                sats = rates.sats_for_fiat(amount, currency="BIF")
                if sats < 1:
                    raise ProviderError("The checkout total is below Blink's minimum invoice amount.")
                invoice = blink.create_invoice_btc(
                    sats,
                    wallet_id=wallet_id,
                    memo=f"FOBOS {order_id}",
                    expires_in_minutes=15,
                )
                settlement_currency = "SAT"
                settlement_amount = Decimal(sats)
            else:
                raise ProviderError(
                    f"Blink returned unsupported receiving wallet currency '{wallet_currency}'."
                )
        except (BlinkError, YadioError) as exc:
            raise ProviderError(str(exc)) from exc

        if not invoice.payment_request:
            raise ProviderError("Blink did not return a Lightning invoice.")
        if invoice.amount_sats is None or invoice.amount_sats <= 0:
            raise ProviderError("Blink did not return a valid satoshi amount for the invoice.")

        return AdapterInvoice(
            order_id=order_id,
            payment_request=invoice.payment_request,
            amount_sats=int(invoice.amount_sats),
            amount_bif=amount,
            settlement_currency=settlement_currency,
            settlement_amount=settlement_amount,
            exchange_rate=(settlement_amount / amount).quantize(Decimal("0.000000000001")),
            rate_source="Yadio.io",
            rate_timestamp=rates.quoted_at,
        )

    def get_status(self, order_id: str):
        from .models import Payment

        payment = Payment.objects.get(order_id=order_id)
        try:
            status = self._blink().invoice_status(payment.payment_request)
        except BlinkError as exc:
            raise ProviderError("Blink could not retrieve the invoice status.") from exc
        return AdapterStatus("confirmed" if status in {"paid", "success", "confirmed"} else status)
