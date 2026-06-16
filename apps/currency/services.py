"""Currency business logic: rate refresh, conversion, formatting.

`convert` is the single conversion entry point used everywhere (catalog, cart,
checkout). It reads cached/last-good rates, applies the admin FX markup, and
rounds per the target currency's rules so prices are consistent across the app.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.common.exceptions import DomainError
from apps.storeconfig.selectors import get_setting

from . import selectors
from .models import Currency, ExchangeRate
from .providers import get_rates_provider
from .selectors import RATES_CACHE_KEY


class RateUnavailable(DomainError):
    default_detail = "No exchange rate is available for that currency."
    default_code = "rate_unavailable"


def refresh_rates(*, symbols: Iterable[str] | None = None) -> dict[str, object]:
    """Fetch fresh rates from the provider into the DB + cache.

    On provider failure the last-good DB rows are left intact (we just don't
    write new ones), so conversions keep working. Returns a status dict.
    """
    base = selectors.base_code()
    codes = list(symbols) if symbols else selectors.active_codes() or [base]
    provider = get_rates_provider()
    try:
        fetched = provider.fetch_rates(base, codes)
    except Exception as exc:  # noqa: BLE001 - any provider error → keep last good
        return {"ok": False, "error": str(exc), "source": provider.name, "base": base}

    now = timezone.now()
    rows = [
        ExchangeRate(base=base, quote=code, rate=rate, source=provider.name, fetched_at=now)
        for code, rate in fetched.items()
    ]
    ExchangeRate.objects.bulk_create(rows)
    _write_cache(base, fetched, now)
    return {"ok": True, "source": provider.name, "base": base, "count": len(rows)}


def _write_cache(base: str, rates: dict[str, Decimal], fetched_at) -> None:
    try:
        cache.set(
            RATES_CACHE_KEY,
            {
                "base": base,
                "rates": {code: str(rate) for code, rate in rates.items()},
                "fetched_at": fetched_at.isoformat(),
            },
            timeout=None,
        )
    except Exception:  # noqa: BLE001 - cache is an optimisation, not required
        pass


def _markup_factor() -> Decimal:
    pct = Decimal(str(get_setting("currency.fx_markup_percent")))
    return Decimal("1") + (pct / Decimal("100"))


def quantize(amount: Decimal, currency: Currency) -> Decimal:
    """Apply a currency's rounding rules (increment + optional charm pricing)."""
    increment = currency.rounding_increment or Decimal("0")
    if increment > 0:
        steps = (amount / increment).to_integral_value(rounding=ROUND_HALF_UP)
        amount = steps * increment
        if currency.charm_pricing:
            amount = amount - Decimal("0.01")
    places = Decimal(10) ** -currency.decimal_places
    return amount.quantize(places, rounding=ROUND_HALF_UP)


def convert(
    amount: Decimal,
    from_code: str,
    to_code: str,
    *,
    apply_markup: bool = True,
    rate: Decimal | None = None,
) -> Decimal:
    """Convert ``amount`` from one currency to another.

    Pass an explicit ``rate`` (cross rate from→to, markup already included) to do
    a deterministic locked conversion — used for rate-locked orders/refunds.
    """
    from_code, to_code = from_code.upper(), to_code.upper()
    to_currency = selectors.get_currency(to_code) or _fallback_currency(to_code)

    if rate is not None:
        return quantize(amount * rate, to_currency)

    if from_code == to_code:
        return quantize(amount, to_currency)

    rates = selectors.get_rates()
    if from_code not in rates or to_code not in rates:
        raise RateUnavailable()

    amount_in_base = amount / rates[from_code]
    converted = amount_in_base * rates[to_code]
    base = selectors.base_code()
    if apply_markup and to_code != base:
        converted *= _markup_factor()
    return quantize(converted, to_currency)


def effective_rate(from_code: str, to_code: str) -> Decimal:
    """The cross rate (incl. markup) used to convert 1 unit from→to.

    Snapshot this onto an order at checkout so the charge/refund is deterministic.
    """
    from_code, to_code = from_code.upper(), to_code.upper()
    if from_code == to_code:
        return Decimal("1")
    rates = selectors.get_rates()
    if from_code not in rates or to_code not in rates:
        raise RateUnavailable()
    rate = rates[to_code] / rates[from_code]
    base = selectors.base_code()
    if to_code != base:
        rate *= _markup_factor()
    return rate


def format_amount(amount: Decimal, currency: Currency) -> str:
    return f"{currency.symbol}{amount:.{currency.decimal_places}f}"


def price_quote(base_amount: Decimal, to_code: str) -> dict[str, object]:
    """A display-ready price: base + converted amount, formatting, and rate used.

    Falls back to the base currency if no rate is available, so browsing never
    breaks (the response signals the fallback via ``converted=False``).
    """
    base = selectors.base_code()
    base_currency = selectors.get_currency(base) or _fallback_currency(base)
    to_code = to_code.upper()
    try:
        amount = convert(base_amount, base, to_code)
        rate = effective_rate(base, to_code)
        currency = selectors.get_currency(to_code) or _fallback_currency(to_code)
        return {
            "base_amount": str(base_amount),
            "base_currency": base,
            "currency": to_code,
            "amount": str(amount),
            "formatted": format_amount(amount, currency),
            "rate": str(rate),
            "converted": True,
        }
    except RateUnavailable:
        return {
            "base_amount": str(base_amount),
            "base_currency": base,
            "currency": base,
            "amount": str(quantize(base_amount, base_currency)),
            "formatted": format_amount(base_amount, base_currency),
            "rate": "1",
            "converted": False,
        }


def _fallback_currency(code: str) -> Currency:
    """An unsaved 2-dp currency used only for formatting when a row is missing."""
    return Currency(code=code, name=code, symbol="", decimal_places=2)
