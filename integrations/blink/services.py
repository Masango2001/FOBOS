"""Blink higher-level services (doc §6, §12).

`BlinkService` turns GraphQL documents into operations the rest of FOBOS can
call without knowing the API shape: `payments/` never imports `queries.py` or
`mutations.py` directly. It also owns the fixed company coordinates of doc §47
(BLINK_USERNAME, BTC/USD wallet ids, optional lightning address) and translates
Blink statuses into the canonical `pending | paid | expired` axis (doc §24).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .client import BlinkClient
from .exceptions import BlinkConfigError, BlinkMutationError
from .mutations import (
    LN_ADDRESS_PAYMENT_SEND_MUTATION,
    LN_INVOICE_CANCEL_MUTATION,
    LN_INVOICE_CREATE_MUTATION,
    LN_INVOICE_PAYMENT_SEND_MUTATION,
    LN_USD_INVOICE_CREATE_MUTATION,
)
from .queries import (
    ACCOUNT_DEFAULT_WALLET_QUERY,
    LN_INVOICE_PAYMENT_STATUS_QUERY,
    REALTIME_PRICE_QUERY,
)

_STATUS_MAP = {
    "PENDING": "pending",
    "PAID": "paid",
    "EXPIRED": "expired",
}


@dataclass(frozen=True)
class BlinkInvoice:
    """A created BOLT11 invoice (doc §9) — the Lightnings-side destination."""

    payment_request: str
    payment_hash: str = ""
    amount_sats: int | None = None
    amount_cents: int | None = None
    status: str = "pending"


def translate_invoice_status(status: str | None) -> str:
    """Map a Blink status to the canonical FOBOS axis (doc §10, §24).

    Unknown statuses pass through lowercased so new provider states never crash
    the translation.
    """
    key = (status or "").upper()
    return _STATUS_MAP.get(key, (status or "").lower())


class BlinkService:
    """Operations FOBOS needs from Blink: wallet lookup, invoices, payments.

    The BTC/USD wallet ids and the lightning address are the *company* fixed
    coordinates (doc §47) — customer-supplied destinations stay in `payments/`
    models, never here.
    """

    def __init__(
        self,
        client: BlinkClient | None = None,
        *,
        btc_wallet_id: str | None = None,
        usd_wallet_id: str | None = None,
        username: str | None = None,
        lightning_address: str | None = None,
    ) -> None:
        self.client = client or BlinkClient()
        self.btc_wallet_id = btc_wallet_id or os.getenv("BLINK_BTC_WALLET_ID") or ""
        self.usd_wallet_id = usd_wallet_id or os.getenv("BLINK_USD_WALLET_ID") or ""
        self.username = username or os.getenv("BLINK_USERNAME") or ""
        self.lightning_address = lightning_address or os.getenv("BLINK_LIGHTNING_ADDRESS") or ""

    def default_wallet(
        self, username: str | None = None, wallet_currency: str = "BTC"
    ) -> dict[str, Any]:
        """Return `accountDefaultWallet` (doc §8) — the company receive wallet.

        Live payload: `{ id, currency }` with `currency` a WalletCurrency enum.
        """
        username = username or self.username
        if not username:
            raise BlinkConfigError("BLINK_USERNAME is not configured.")
        variables: dict[str, Any] = {"username": username}
        if wallet_currency:
            variables["walletCurrency"] = wallet_currency
        data = self.client.execute(ACCOUNT_DEFAULT_WALLET_QUERY, variables)
        wallet = data.get("accountDefaultWallet")
        if not wallet:
            raise BlinkMutationError(
                "No default wallet for the account.", path="accountDefaultWallet"
            )
        return wallet

    def realtime_price(self, currency: str = "USD") -> dict[str, Any]:
        """Return the BTC price in a display currency (reference `realtimePrice`).

        Payload: `{ btcSatPrice: { base, offset } }` — base/offset encode the
        price of one sat; used by the frontend for SATS→BIF conversions.
        """
        data = self.client.execute(REALTIME_PRICE_QUERY, {"currency": currency})
        return data.get("realtimePrice") or {}

    def create_invoice_btc(
        self,
        amount_sats: int,
        *,
        wallet_id: str | None = None,
        memo: str | None = None,
        expires_in_minutes: int | None = None,
    ) -> BlinkInvoice:
        """Create a BTC invoice in sats on behalf of a recipient wallet (doc §8/§9)."""
        wallet_id = wallet_id or self.btc_wallet_id
        if not wallet_id:
            raise BlinkConfigError("BLINK_BTC_WALLET_ID is not configured.")
        input_ = {"amount": int(amount_sats), "recipientWalletId": wallet_id}
        if memo:
            input_["memo"] = memo
        if expires_in_minutes is not None:
            input_["expiresIn"] = int(expires_in_minutes)
        return self._create_invoice(
            LN_INVOICE_CREATE_MUTATION,
            "lnInvoiceCreateOnBehalfOfRecipient",
            {"input": input_},
            amount_key="satoshis",
        )

    def create_invoice_usd_cents(
        self,
        amount_cents: int,
        *,
        wallet_id: str | None = None,
        memo: str | None = None,
    ) -> BlinkInvoice:
        """Create a USD invoice in cents (doc §8)."""
        wallet_id = wallet_id or self.usd_wallet_id
        if not wallet_id:
            raise BlinkConfigError("BLINK_USD_WALLET_ID is not configured.")
        input_ = {"amount": int(amount_cents), "recipientWalletId": wallet_id}
        if memo:
            input_["memo"] = memo
        return self._create_invoice(
            LN_USD_INVOICE_CREATE_MUTATION,
            "lnUsdInvoiceCreateOnBehalfOfRecipient",
            {"input": input_},
            amount_key="cents",
        )

    def _create_invoice(
        self,
        mutation: str,
        path: str,
        variables: dict[str, Any],
        *,
        amount_key: str,
    ) -> BlinkInvoice:
        data = self.client.execute(mutation, variables)
        _raise_mutation_errors(data, path)
        result = data.get(path) or {}
        invoice = result.get("invoice") or {}
        return BlinkInvoice(
            payment_request=invoice.get("paymentRequest") or "",
            payment_hash=invoice.get("paymentHash") or "",
            amount_sats=invoice.get("satoshis"),
            amount_cents=invoice.get("cents"),
            status=translate_invoice_status(invoice.get("paymentStatus")),
        )

    def invoice_status(self, payment_request: str) -> str:
        """Poll the status of a BOLT11 invoice (doc §8, §25 fallback).

        Returns the canonical status: ``pending | paid | expired``. The live
        payload is `{ status: InvoicePaymentStatus }`.
        """
        data = self.client.execute(
            LN_INVOICE_PAYMENT_STATUS_QUERY, {"paymentRequest": payment_request}
        )
        result = data.get("lnInvoicePaymentStatusByPaymentRequest") or {}
        if not isinstance(result, dict):
            return translate_invoice_status(result)
        return translate_invoice_status(result.get("status"))

    def cancel_invoice(self, payment_hash: str, *, wallet_id: str | None = None) -> bool:
        """Cancel a pending invoice by its payment hash (live schema, doc §8).

        `payment_hash` comes from the `BlinkInvoice.payment_hash` returned at
        creation — Blink has no cancel-by-paymentRequest operation.
        """
        wallet_id = wallet_id or self.btc_wallet_id
        if not wallet_id:
            raise BlinkConfigError("BLINK_BTC_WALLET_ID is not configured.")
        data = self.client.execute(
            LN_INVOICE_CANCEL_MUTATION,
            {"input": {"paymentHash": payment_hash, "walletId": wallet_id}},
        )
        _raise_mutation_errors(data, "lnInvoiceCancel")
        return bool((data.get("lnInvoiceCancel") or {}).get("success"))

    def pay_invoice(self, payment_request: str, *, wallet_id: str | None = None) -> str:
        """Pay a BOLT11 invoice from the BTC wallet (doc §20.7, §49).

        `wallet_id` is the *source* of the sats — when FOBOS itself pays the
        BitLibera off-ramp invoice, BLINK_BTC_WALLET_ID is the default source;
        when the customer pays from their own wallet, this method is not used.
        """
        wallet_id = wallet_id or self.btc_wallet_id
        if not wallet_id:
            raise BlinkConfigError("BLINK_BTC_WALLET_ID is not configured.")
        data = self.client.execute(
            LN_INVOICE_PAYMENT_SEND_MUTATION,
            {"input": {"paymentRequest": payment_request, "walletId": wallet_id}},
        )
        _raise_mutation_errors(data, "lnInvoicePaymentSend")
        return translate_invoice_status((data.get("lnInvoicePaymentSend") or {}).get("status"))

    def pay_lightning_address(
        self,
        destination: str,
        amount_sats: int,
        *,
        wallet_id: str | None = None,
        memo: str | None = None,
    ) -> str:
        """Send sats to a Lightning Address (doc §8, §50) — not a BOLT11 invoice.

        Live input field is `lnAddress` (the `destination` argument maps to it).
        Returns the canonical status (PaymentSendResult: success|pending|...).
        """
        wallet_id = wallet_id or self.btc_wallet_id
        if not wallet_id:
            raise BlinkConfigError("BLINK_BTC_WALLET_ID is not configured.")
        input_: dict[str, Any] = {
            "lnAddress": destination,
            "amount": int(amount_sats),
            "walletId": wallet_id,
        }
        if memo:
            input_["memo"] = memo
        data = self.client.execute(LN_ADDRESS_PAYMENT_SEND_MUTATION, {"input": input_})
        _raise_mutation_errors(data, "lnAddressPaymentSend")
        return translate_invoice_status((data.get("lnAddressPaymentSend") or {}).get("status"))


def _raise_mutation_errors(data: dict[str, Any], path: str) -> None:
    """Raise `BlinkMutationError` when a mutation reports field-level errors."""
    result = data.get(path) or {}
    errors = result.get("errors") or []
    if errors:
        raise BlinkMutationError(
            errors[0].get("message") or "Blink mutation failed.",
            path=path,
            errors=errors,
        )
