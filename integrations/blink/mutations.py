"""Blink GraphQL *mutations* (actions) — doc §7: creating/acting is a `mutation`.

Each constant is a self-contained mutation; the resulting *field* errors are
checked by the service layer and raised as `BlinkMutationError`. Input/field
names mirror the LIVE blink public schema (introspected 2026):

- invoice payloads expose `LnInvoice { paymentRequest, paymentHash, satoshis,
  paymentStatus }` — there is NO `cents` field even on USD invoices.
- `lnInvoiceCancel` takes `LnInvoiceCancelInput { paymentHash, walletId }`
  (there is no cancel-by-paymentRequest).
- `lnInvoicePaymentSend` input type is `LnInvoicePaymentInput`.
- `lnAddressPaymentSend` input uses `lnAddress` (not `destination`).
"""

from __future__ import annotations

#: Create a BTC invoice on behalf of a recipient wallet (doc §8).
#: `amount` is an integer of sats (`SatAmount`); `expiresIn` is an integer of
#: minutes, the documented BTC default is 24 hours when omitted (doc §9).
#:
#: Variables:
#:   input.amount:             int    — invoice amount in sats.
#:   input.recipientWalletId:  str    — Blink wallet id that receives the sats.
#:   input.memo:               str|None — optional human readable label.
#:   input.expiresIn:          int|None — optional lifetime in minutes.
LN_INVOICE_CREATE_MUTATION = """
mutation LnInvoiceCreateOnBehalfOfRecipient($input: LnInvoiceCreateOnBehalfOfRecipientInput!) {
    lnInvoiceCreateOnBehalfOfRecipient(input: $input) {
        errors {
            message
        }
        invoice {
            paymentRequest
            paymentHash
            satoshis
            paymentStatus
        }
    }
}
"""

#: Create a USD invoice on behalf of a recipient wallet (doc §8).
#: `amount` is an integer of USD *cents* (`CentAmount`). The returned
#: `LnInvoice` carries `satoshis` (no `cents` field) — the same selection as the
#: BTC mutation.
#:
#: Variables:
#:   input.amount:             int    — invoice amount in USD cents.
#:   input.recipientWalletId:  str    — Blink wallet id that receives the USD.
#:   input.memo:               str|None — optional human readable label.
LN_USD_INVOICE_CREATE_MUTATION = """
mutation LnUsdInvoiceCreateOnBehalfOfRecipient($input: LnUsdInvoiceCreateOnBehalfOfRecipientInput!) {
    lnUsdInvoiceCreateOnBehalfOfRecipient(input: $input) {
        errors {
            message
        }
        invoice {
            paymentRequest
            paymentHash
            satoshis
            paymentStatus
        }
    }
}
"""

#: Cancel a Lightning invoice by its payment hash (live schema has no cancel
#: by paymentRequest — doc §8).
#:
#: Variables:
#:   input.paymentHash:  str — BOLT11 invoice payment hash.
#:   input.walletId:     str — Blink wallet id that issued the invoice.
LN_INVOICE_CANCEL_MUTATION = """
mutation LnInvoiceCancel($input: LnInvoiceCancelInput!) {
    lnInvoiceCancel(input: $input) {
        errors {
            message
        }
        success
    }
}
"""

#: Pay a BOLT11 invoice from a BTC wallet balance (doc §20.7, §49).
#: Input type is `LnInvoicePaymentInput` (live schema). Distinct from
#: `LnAddressPaymentSend` which targets a Lightning Address.
#:
#: Variables:
#:   input.paymentRequest:  str — BOLT11 invoice to pay.
#:   input.walletId:        str — source Blink wallet id.
#:   input.memo:            str|None — optional note for the payment.
LN_INVOICE_PAYMENT_SEND_MUTATION = """
mutation LnInvoicePaymentSend($input: LnInvoicePaymentInput!) {
    lnInvoicePaymentSend(input: $input) {
        errors {
            message
        }
        status
    }
}
"""

#: Send sats to a Lightning Address (doc §8, §50) — *not* a BOLT11 payment.
#: Live input field is `lnAddress` (string), not `destination`.
#:
#: Variables:
#:   input.lnAddress:    str — Lightning Address (user@domain).
#:   input.amount:       int — amount in sats.
#:   input.walletId:     str — source Blink wallet id.
LN_ADDRESS_PAYMENT_SEND_MUTATION = """
mutation LnAddressPaymentSend($input: LnAddressPaymentSendInput!) {
    lnAddressPaymentSend(input: $input) {
        errors {
            message
        }
        status
    }
}
"""
