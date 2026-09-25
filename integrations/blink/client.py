"""Blink GraphQL HTTP client (doc §6, §11).

Single HTTP entry point: POST to the GraphQL endpoint with the `X-API-KEY`
header, a requested `timeout` and response/error handling. `queries.py`,
`mutations.py` and `subscriptions.py` only provide the GraphQL documents — this
class is the only place that talks HTTP to Blink.

Configuration comes from `BLINK_API_URL` / `BLINK_API_KEY` (doc §18) and can be
overridden per-client. An optional `session` (e.g. `requests.Session`) is
accepted for pooling/reuse by higher layers.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .exceptions import (
    BlinkAPIError,
    BlinkAuthError,
    BlinkConfigError,
    BlinkGraphQLError,
    BlinkRateLimitError,
    BlinkTimeoutError,
    BlinkTransportError,
)

DEFAULT_TIMEOUT_SECONDS = 30


class BlinkClient:
    """Minimal GraphQL-over-HTTP client for the Blink public API."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: Any = None,
    ) -> None:
        self.url = url or os.getenv("BLINK_API_URL") or ""
        self.api_key = api_key if api_key is not None else (os.getenv("BLINK_API_KEY") or "")
        if not self.url:
            raise BlinkConfigError("BLINK_API_URL is not configured.")
        if not self.api_key:
            raise BlinkConfigError("BLINK_API_KEY is not configured.")
        self.timeout = timeout
        self.session = (
            session  # requests.Session or requests-like object; None => module-level helpers
        )

    def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Run a GraphQL document and return its `data` block.

        Raises :class:`BlinkConfigError` on bad configuration,
        :class:`BlinkAuthError` on HTTP 401/403,
        :class:`BlinkRateLimitError` on HTTP 429,
        :class:`BlinkGraphQLError` when the operation reports GraphQL errors,
        :class:`BlinkTimeoutError` on timeouts and :class:`BlinkTransportError`
        on other transport failures.
        """
        payload: dict[str, Any] = {"query": query, "variables": variables or {}}
        if operation_name:
            payload["operationName"] = operation_name

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        transport = self.session or requests
        try:
            response = transport.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        except requests.Timeout as exc:
            raise BlinkTimeoutError(f"Blink request timed out after {self.timeout}s.") from exc
        except requests.RequestException as exc:
            raise BlinkTransportError(f"Blink request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise BlinkAuthError(
                "Blink rejected the X-API-KEY.",
                status_code=response.status_code,
                payload=_json_or_none(response),
            )
        if response.status_code == 429:
            raise BlinkRateLimitError(
                "Blink rate limit exceeded.",
                status_code=response.status_code,
                payload=_json_or_none(response),
            )
        if not 200 <= response.status_code < 300:
            raise BlinkAPIError(
                f"Blink returned HTTP {response.status_code}.",
                status_code=response.status_code,
                payload=_json_or_none(response),
            )

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise BlinkAPIError(
                "Blink returned a non-JSON body.",
                status_code=response.status_code,
            ) from exc

        errors = body.get("errors")
        if errors:
            detail = "; ".join(str(e.get("message", "?")) for e in errors)
            raise BlinkGraphQLError(detail, errors=errors)
        return body.get("data") or {}


def _json_or_none(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
