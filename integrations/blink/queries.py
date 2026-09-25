"""Blink GraphQL *queries* (reads) — doc §7: reading in GraphQL is a `query`.

Each constant is one self-contained query with its variables documented, so the
client layer never inlines GraphQL in services (`payments/` must stay GraphQL-agnostic).

Field/input names mirror the LIVE blink public schema (introspected 2026):
`accountDefaultWallet → { id, currency }`, `lnInvoicePaymentStatusByPaymentRequest`
takes `input: { paymentRequest }` — the legacy `lnInvoicePaymentStatus` operation
does NOT exist and must never be used.
"""

from __future__ import annotations

#: Default wallet of a Blink account, optionally constrained by currency.
#: Live schema: `accountDefaultWallet` returns `PublicWallet { id, currency }`
#: where `currency` is a WalletCurrency enum (BTC|USD).
#:
#: Variables:
#:   username:        str   — Blink username of the account (doc §47).
#:   walletCurrency:  "BTC" | "USD" (optional, defaults to the account default).
ACCOUNT_DEFAULT_WALLET_QUERY = """
query AccountDefaultWallet($username: Username!, $walletCurrency: WalletCurrency) {
    accountDefaultWallet(username: $username, walletCurrency: $walletCurrency) {
        id
        currency
    }
}
"""

#: Payment status of a BOLT11 request — the polling fallback of the WebSocket
#: subscription (doc §25, §52). Live schema: the operation takes
#: `input: { paymentRequest }` and returns `status: InvoicePaymentStatus`
#: (PENDING | PAID | EXPIRED).
#:
#: Variables:
#:   paymentRequest:  str — BOLT11 payment_request whose status is queried.
LN_INVOICE_PAYMENT_STATUS_QUERY = """
query LnInvoicePaymentStatusByPaymentRequest($paymentRequest: LnPaymentRequest!) {
    lnInvoicePaymentStatusByPaymentRequest(input: { paymentRequest: $paymentRequest }) {
        status
    }
}
"""

#: Live BTC price in the requested display currency (reference `realtimePrice`).
#: `btcSatPrice.base/offset` let the frontend render amounts without an external
#: price oracle.
#:
#: Variables:
#:   currency:  DisplayCurrency — e.g. "USD".
REALTIME_PRICE_QUERY = """
query RealtimePrice($currency: DisplayCurrency!) {
    realtimePrice(currency: $currency) {
        btcSatPrice {
            base
            offset
        }
    }
}
"""
