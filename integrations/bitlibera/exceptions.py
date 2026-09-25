"""BitLibera integration errors (doc §13).

Every BitLibera-specific failure derives from :class:`BitLiberaError` so higher
layers can catch one type. Mirror of the Blink hierarchy: auth (401/403),
rate-limiting (429), transport/timeout, HTTP errors and business rejections the
gateway answers with ``success: false`` while still returning HTTP 200.
"""

from __future__ import annotations


class BitLiberaError(Exception):
    """Base class for every BitLibera-specific failure."""


class BitLiberaConfigError(BitLiberaError):
    """Missing/invalid configuration (base URL, API key).

    Raised lazily by the client constructor — importing the package never
    requires a configured environment (demo adapters run without it).
    """


class BitLiberaTransportError(BitLiberaError):
    """The HTTP request could not be completed (DNS, connection, TLS...)."""


class BitLiberaTimeoutError(BitLiberaTransportError):
    """The gateway did not answer within the configured timeout."""


class BitLiberaAPIError(BitLiberaError):
    """The gateway answered with a non-2xx status or a ``success: false`` body.

    ``status_code`` is the HTTP status when known; ``payload`` is the raw
    gateway body when it was parseable JSON.
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


class BitLiberaAuthError(BitLiberaAPIError):
    """HTTP 401/403 — the ``x-api-key`` is missing, invalid or out of scope."""


class BitLiberaRateLimitError(BitLiberaAPIError):
    """HTTP 429 — the caller is rate-limited; a retry with backoff is safe."""


class BitLiberaOrderError(BitLiberaAPIError):
    """The gateway rejected the order (``success: false``) or reported an order
    that cannot settle (e.g. a refused Lumicash OTP)."""
