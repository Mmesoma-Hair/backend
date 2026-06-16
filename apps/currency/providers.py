"""Provider-agnostic FX rate fetching.

``RatesProvider.fetch_rates(base, symbols)`` returns ``{code: Decimal}`` quoted
against ``base`` (1 base = rate × quote). Swapping providers is a settings change
(``RATES_PROVIDER``); business logic never imports a concrete provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from decimal import Decimal

import requests
from django.conf import settings


class RatesProvider(ABC):
    name = "base"

    @abstractmethod
    def fetch_rates(self, base: str, symbols: Iterable[str]) -> dict[str, Decimal]:
        """Return rates for ``symbols`` quoted against ``base`` (base included as 1)."""


class MockRatesProvider(RatesProvider):
    """Deterministic offline rates for tests / key-less dev."""

    name = "mock"
    # Rates expressed against USD; re-based for any requested base below.
    _USD = {
        "USD": Decimal("1"),
        "EUR": Decimal("0.92"),
        "GBP": Decimal("0.79"),
        "NGN": Decimal("1500"),
        "JPY": Decimal("155"),
    }

    def fetch_rates(self, base: str, symbols: Iterable[str]) -> dict[str, Decimal]:
        base = base.upper()
        base_per_usd = self._USD.get(base, Decimal("1"))
        out: dict[str, Decimal] = {}
        for sym in symbols:
            sym = sym.upper()
            usd_rate = self._USD.get(sym)
            if usd_rate is None:
                continue
            # 1 base = (usd_rate / base_per_usd) quote
            out[sym] = usd_rate / base_per_usd
        out[base] = Decimal("1")
        return out


class CurrencyApiNetProvider(RatesProvider):
    """Adapter for currencyapi.net (the API referenced by the client)."""

    name = "currencyapi_net"
    BASE_URL = "https://currencyapi.net/api/v1/rates"

    def fetch_rates(self, base: str, symbols: Iterable[str]) -> dict[str, Decimal]:
        key = settings.CURRENCY_API_NET_KEY
        if not key:
            raise RuntimeError("CURRENCY_API_NET_KEY is not configured.")
        resp = requests.get(
            self.BASE_URL,
            params={"key": key, "base": base.upper(), "output": "JSON"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        wanted = {s.upper() for s in symbols}
        out = {code: Decimal(str(value)) for code, value in rates.items() if code.upper() in wanted}
        out[base.upper()] = Decimal("1")
        return out


class FrankfurterProvider(RatesProvider):
    """Free, no-key ECB rates (frankfurter.app). A drop-in seam alternative."""

    name = "frankfurter"
    BASE_URL = "https://api.frankfurter.app/latest"

    def fetch_rates(self, base: str, symbols: Iterable[str]) -> dict[str, Decimal]:
        wanted = [s.upper() for s in symbols if s.upper() != base.upper()]
        resp = requests.get(
            self.BASE_URL,
            params={"from": base.upper(), "to": ",".join(wanted)},
            timeout=10,
        )
        resp.raise_for_status()
        rates = resp.json().get("rates", {})
        out = {code: Decimal(str(value)) for code, value in rates.items()}
        out[base.upper()] = Decimal("1")
        return out


# Registry. ExchangeRate-API / Open Exchange Rates plug in here the same way.
_PROVIDERS: dict[str, type[RatesProvider]] = {
    "mock": MockRatesProvider,
    "currencyapi_net": CurrencyApiNetProvider,
    "frankfurter": FrankfurterProvider,
}


def get_rates_provider() -> RatesProvider:
    name = getattr(settings, "RATES_PROVIDER", "mock")
    provider_cls = _PROVIDERS.get(name, MockRatesProvider)
    return provider_cls()
