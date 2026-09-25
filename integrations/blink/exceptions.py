"""Blink integration errors (doc §6).

Everything the Blink client/service can raise derives from a single
``BlinkError`` so higher layers can catch one type and tell real failures from
provider-side quirks. Error names follow the Blink API surface: auth (401),
rate-limiting (429), transport timeouts and GraphQL field/operation errors.
"""

from __future__ import annotations


class BlinkError(Exception):
    """Base class for every Blink-specific failure."""


class BlinkConfigError(BlinkError):
    """Missing/invalid configuration (URL, API key, wallet id).

    Raised lazily by the client/service constructors — importing the package
    never requires a configured environment (demo adapters run without it).
    """


class BlinkTransportError(BlinkError):
    """The HTTP request could not be completed (DNS, connection, TLS...)."""


class BlinkTimeoutError(BlinkTransportError):
    """The provider did not answer within the configured timeout."""


class BlinkAPIError(BlinkError):
    """The provider answered with a non-2xx HTTP status or an empty body.

    ``status_code`` is the HTTP status; ``payload`` is the raw provider body
    when it was parseable JSON.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class BlinkAuthError(BlinkAPIError):
    """HTTP 401/403 — the X-API-KEY is missing, invalid or out of scope."""


class BlinkRateLimitError(BlinkAPIError):
    """HTTP 429 — the caller is rate-limited; a retry with backoff is safe."""


class BlinkGraphQLError(BlinkError):
    """The GraphQL operation returned an ``errors`` payload (query/mutation).

    Blink also returns field-level ``errors`` *inside* mutation results (e.g. a
    failing ``lnInvoiceCreateOnBehalfOfRecipient``); those are surfaced by the
    services as :class:`BlinkMutationError` with ``path`` of the failing field.
    """

    def __init__(self, message: str, errors: list[dict] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class BlinkMutationError(BlinkError):
    """A Blink mutation completed its GraphQL call but returned errors.

    ``path`` names the operation (e.g. ``lnInvoiceCreateOnBehalfOfRecipient``)
    whose ``errors[].message`` blocks the action — the usual way Blink reports
    business rules (WalletInactive, NoAmount, ReceiverDoesNotExist...).
    """

    def __init__(self, message: str, path: str = "", errors: list[dict] | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.errors = errors or []


class BlinkSubscriptionError(BlinkError):
    """The WebSocket subscription failed (protocol, connection or auth)."""


class BlinkSubscriptionUnavailable(BlinkError):
    """The ``websockets`` package is not installed — polling remains the fallback.

    Doc §25/§52 recommends WebSocket → polling: this error tells the caller to
    fall back to ``BlinkService.invoice_status`` when real-time is not available.
    """
