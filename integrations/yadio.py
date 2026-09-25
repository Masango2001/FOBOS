"""Yadio FX quotes used to price BIF checkout invoices in Blink wallets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import os

import requests
from django.core.cache import cache


class YadioError(RuntimeError):
    """Yadio did not provide a current, usable BTC fiat rate."""


@dataclass(frozen=True)
class YadioRates:
    bif_per_btc: Decimal
    usd_per_btc: Decimal
    quoted_at: datetime

    def fiat_amount(self, amount: Decimal, *, source: str, target: str) -> Decimal:
        """Convert major currency units using the BTC-anchored Yadio quote."""
        rates = {"BIF": self.bif_per_btc, "USD": self.usd_per_btc}
        try:
            source_rate = rates[source]
            target_rate = rates[target]
        except KeyError as exc:
            raise YadioError(f"Yadio conversion from {source} to {target} is unsupported.") from exc
        converted = Decimal(amount) * target_rate / source_rate
        return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def sats_for_fiat(self, amount: Decimal, *, currency: str) -> int:
        """Convert a BIF or USD amount to the nearest whole satoshi."""
        rates = {"BIF": self.bif_per_btc, "USD": self.usd_per_btc}
        try:
            fiat_per_btc = rates[currency]
        except KeyError as exc:
            raise YadioError(f"Yadio conversion from {currency} to SAT is unsupported.") from exc
        sats = Decimal(amount) * Decimal(100_000_000) / fiat_per_btc
        return int(sats.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_yadio_rates() -> YadioRates:
    """Fetch fresh rates, reusing a short-lived cache to avoid hammering Yadio."""
    cached = cache.get("fobos:yadio:btc-fiat-rates")
    if isinstance(cached, YadioRates):
        return cached

    base_url = (os.getenv("YADIO_API_URL") or "https://api.yadio.io").rstrip("/")
    try:
        response = requests.get(f"{base_url}/exrates/BTC", timeout=8)
        response.raise_for_status()
        payload = response.json()
        rate_table = payload["BTC"]
        quoted_at = datetime.fromtimestamp(float(payload["timestamp"]) / 1000, tz=UTC)
        bif_per_btc = Decimal(str(rate_table["BIF"]))
        usd_per_btc = Decimal(str(rate_table["USD"]))
    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
        ArithmeticError,
        OSError,
    ) as exc:
        raise YadioError("Could not retrieve the current BIF/USD to BTC quote from Yadio.") from exc

    now = datetime.now(UTC)
    max_age = int(os.getenv("YADIO_RATE_MAX_AGE_SECONDS") or "300")
    age_seconds = (now - quoted_at).total_seconds()
    if (
        bif_per_btc <= 0
        or usd_per_btc <= 0
        or age_seconds < -60
        or age_seconds > max_age
    ):
        raise YadioError("Yadio returned an invalid or stale exchange-rate quote.")

    rates = YadioRates(bif_per_btc, usd_per_btc, quoted_at)
    cache_seconds = int(os.getenv("YADIO_RATE_CACHE_SECONDS") or "15")
    if cache_seconds > 0:
        cache.set("fobos:yadio:btc-fiat-rates", rates, timeout=cache_seconds)
    return rates
