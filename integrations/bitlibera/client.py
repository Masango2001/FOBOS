"""BitLibera REST client (doc §13, §16).

GET/POST against the base URL with the `x-api-key` header, a requested timeout
and typed error handling. Routes come from `endpoints.py`; higher-level use goes
through `BitLiberaService`. Every endpoint is authenticated with the partner
key (doc §1 authentication header), so a missing key fails fast at call time.
An optional `session` is accepted for pooling/reuse.

The merchant-registration discovery endpoint (`auth/register`) is intentionally
NOT part of the integration: merchant credentials are provisioned out-of-band
by the operator and never through FOBOS (doc §18).
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .exceptions import (
    BitLiberaAPIError,
    BitLiberaAuthError,
    BitLiberaConfigError,
    BitLiberaOrderError,
    BitLiberaRateLimitError,
    BitLiberaTimeoutError,
    BitLiberaTransportError,
)

DEFAULT_TIMEOUT_SECONDS = 30


class BitLiberaClient:
    """Minimal REST client for the BitLibera gateway."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: Any = None,
    ) -> None:
        base = base_url or os.getenv("BITLIBERA_BASE_URL") or ""
        if not base:
            raise BitLiberaConfigError("BITLIBERA_BASE_URL is not configured.")
        self.base_url = base.rstrip("/")
        self.api_key = api_key if api_key is not None else (os.getenv("BITLIBERA_API_KEY") or "")
        self.timeout = timeout
        self.session = session

    def post(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST JSON to an endpoint and return the parsed response body."""
        headers = self._headers()
        transport = self.session or requests
        try:
            response = transport.post(
                self.base_url + endpoint,
                json=data or {},
                headers=headers,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise BitLiberaTimeoutError(
                f"BitLibera request timed out after {self.timeout}s."
            ) from exc
        except requests.RequestException as exc:
            raise BitLiberaTransportError(f"BitLibera request failed: {exc}") from exc
        return self._parse(response)

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET an endpoint (e.g. order status) and return the parsed body."""
        headers = self._headers()
        transport = self.session or requests
        try:
            response = transport.get(
                self.base_url + endpoint,
                params=params or {},
                headers=headers,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise BitLiberaTimeoutError(
                f"BitLibera request timed out after {self.timeout}s."
            ) from exc
        except requests.RequestException as exc:
            raise BitLiberaTransportError(f"BitLibera request failed: {exc}") from exc
        return self._parse(response)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise BitLiberaConfigError("BITLIBERA_API_KEY is not configured.")
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _parse(self, response: Any) -> dict[str, Any]:
        if response.status_code in (401, 403):
            raise BitLiberaAuthError(
                "BitLibera rejected the x-api-key.",
                status_code=response.status_code,
                payload=_json_or_none(response),
            )
        if response.status_code == 429:
            raise BitLiberaRateLimitError(
                "BitLibera rate limit exceeded.",
                status_code=response.status_code,
                payload=_json_or_none(response),
            )
        if not 200 <= response.status_code < 300:
            raise BitLiberaAPIError(
                f"BitLibera returned HTTP {response.status_code}.",
                status_code=response.status_code,
                payload=_json_or_none(response),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise BitLiberaAPIError(
                "BitLibera returned a non-JSON body.",
                status_code=response.status_code,
            ) from exc
        if isinstance(body, dict) and body.get("success") is False:
            raise BitLiberaOrderError(
                body.get("message") or "BitLibera rejected the order.",
                status_code=response.status_code,
                payload=body,
            )
        return body


def _json_or_none(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
