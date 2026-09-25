"""Blink GraphQL *subscriptions* over WebSocket (doc §7, §25, §52).

The WebSocket lives here (`integrations/blink/subscriptions.py`) and only here:
the HTTP webhook endpoint stays in `payments/webhooks.py`, the status *polling*
fallback stays in `BlinkService.invoice_status`.

Transport protocol: POST /graphql uses the same `X-API-KEY`, but the socket
subscribes with the `graphql-transport-ws` subprotocol (doc §25) on
`wss://ws.blink.sv/graphql`.

The GQL document and the wire frame builders are pure functions (no network, no
external dependency): they are safe to import anywhere and unit-testable. The
socket transport lazily imports the `websockets` sync client, so the package
imports cleanly even on installs where real-time is not needed — the polling
fallback then covers the gap.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from .exceptions import (
    BlinkAuthError,
    BlinkSubscriptionError,
    BlinkSubscriptionUnavailable,
    BlinkTimeoutError,
)

#: The real-time counterpart of `LN_INVOICE_PAYMENT_STATUS_QUERY` (doc §8, §25).
#: Same live input shape as the query: `input: { paymentRequest }`.
#:
#: Variables:
#:   paymentRequest:  str — BOLT11 invoice whose payment status is watched.
SUBSCRIPTION_INVOICE_STATUS = """
subscription LnInvoicePaymentStatusByPaymentRequest($paymentRequest: LnPaymentRequest!) {
    lnInvoicePaymentStatusByPaymentRequest(input: { paymentRequest: $paymentRequest })
}
"""

#: Default socket endpoint — the WS counterpart of `BLINK_API_URL` (doc §25).
BLINK_WSS_DEFAULT_URL = "wss://ws.blink.sv/graphql"

#: Subprotocol mandated by the integration document (§25): graphql-transport-ws.
GRAPHQL_TRANSPORT_SUBPROTOCOL = "graphql-transport-ws"


def build_connection_init(api_key: str | None = None) -> dict[str, Any]:
    """Return the `connection_init` frame authenticating the socket (doc §52)."""
    payload = {"headers": {"X-API-KEY": api_key}} if api_key else {}
    return {"type": "connection_init", "payload": payload}


def build_subscribe_payload(payment_request: str, request_id: str) -> dict[str, Any]:
    """Return the `subscribe` frame for `graphql-transport-ws` (doc §52)."""
    return {
        "id": request_id,
        "type": "subscribe",
        "payload": {
            "query": SUBSCRIPTION_INVOICE_STATUS,
            "variables": {"paymentRequest": payment_request},
        },
    }


def parse_status_message(message: dict[str, Any]) -> str:
    """Extract the Blink status from a `next` frame; raise on `error`/`complete`.

    Returns the raw Blink status (PENDING | PAID | EXPIRED). Control frames
    (`connection_ack`, `ping`/`pong`) are handled by :func:`iter_statuses` and
    never reach this helper.
    """
    message_type = message.get("type")
    if message_type == "error":
        errors = message.get("payload") or []
        detail = errors[0].get("message") if errors else "Unknown subscription error."
        raise BlinkSubscriptionError(detail)
    if message_type == "complete":
        raise BlinkSubscriptionError("Subscription completed by the server.")
    if message_type != "next":
        raise BlinkSubscriptionError(f"Unexpected WebSocket frame type: {message_type!r}.")

    data = message.get("payload", {}).get("data", {})
    result = data.get("lnInvoicePaymentStatusByPaymentRequest")
    if isinstance(result, dict):
        status = result.get("status")
    else:
        status = result
    if not status:
        raise BlinkSubscriptionError("Status frame carried no invoice status.")
    return status


def iter_statuses(
    payment_request: str,
    *,
    ws_url: str | None = None,
    api_key: str | None = None,
    request_id: str | None = None,
    connect_timeout: float = 10.0,
) -> Iterator[str]:
    """Blocking iterator of Blink status strings (PENDING/PAID/EXPIRED).

    Opens one persistent socket, sends the `subscribe` frame and yields every
    status change Blink pushes. The caller stops iterating (closing the socket)
    once its business rule is met — e.g. a PAID invoice. Under the WebSocket-
    first policy (doc §25), a raised or exhausted iterator should fall back to
    polling via `BlinkService.invoice_status`.

    Lazy-imports the `websockets` sync client; raises
    :class:`BlinkSubscriptionUnavailable` when the optional dependency is missing.
    """
    try:
        from websockets.exceptions import InvalidStatus  # type: ignore[import-not-found]
        from websockets.sync.client import connect  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on install
        raise BlinkSubscriptionUnavailable(
            "The 'websockets' package is not installed; "
            "fall back to BlinkService.invoice_status (polling)."
        ) from exc

    url = ws_url or BLINK_WSS_DEFAULT_URL
    request_id = request_id or payment_request[:32]

    options = {"subprotocols": [GRAPHQL_TRANSPORT_SUBPROTOCOL], "open_timeout": connect_timeout}
    if api_key:
        options["additional_headers"] = {"X-API-KEY": api_key}

    try:
        with connect(url, **options) as socket:  # type: ignore[arg-type]
            socket.send(json.dumps(build_connection_init(api_key)))
            socket.send(json.dumps(build_subscribe_payload(payment_request, request_id)))
            for raw in socket:
                message = json.loads(raw)
                message_type = message.get("type")
                if message_type == "connection_ack":
                    continue
                if message_type == "ping":
                    socket.send('{"type": "pong"}')
                    continue
                yield parse_status_message(message)
                if message_type == "complete":
                    return
    except InvalidStatus as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (401, 403):
            raise BlinkAuthError("Blink rejected the WebSocket X-API-KEY.") from exc
        raise BlinkSubscriptionError(f"Blink WebSocket handshake failed: {exc}") from exc
    except OSError as exc:  # pragma: no cover - network dependent
        raise BlinkTimeoutError(f"Blink WebSocket connect failed: {exc}") from exc


def on_status_change(
    payment_request: str,
    callback,
    *,
    stop_on=(),
    ws_url: str | None = None,
    api_key: str | None = None,
    request_id: str | None = None,
    connect_timeout: float = 10.0,
) -> None:
    """Subscribe and invoke ``callback(status)`` per change until a stop value.

    ``stop_on`` is a tuple of Blink statuses that ends the socket early (e.g.
    ``("PAID", "EXPIRED")``). Any :class:`BlinkSubscriptionError` is left to
    the caller, which may fall back to polling (doc §25, §52).
    """
    stops = set(stop_on)
    for status in iter_statuses(
        payment_request,
        ws_url=ws_url,
        api_key=api_key,
        request_id=request_id,
        connect_timeout=connect_timeout,
    ):
        callback(status)
        if status in stops:
            return
