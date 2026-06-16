"""Currency read logic: active currencies, base code, cached rate maps."""

from __future__ import annotations

from decimal import Decimal

from django.core.cache import cache

from apps.storeconfig.selectors import get_setting

from .models import Currency, ExchangeRate

RATES_CACHE_KEY = "currency:rates"


def base_code() -> str:
    return str(get_setting("currency.base")).upper()


def active_currencies() -> list[Currency]:
    return list(Currency.objects.filter(is_active=True))


def active_codes() -> list[str]:
    return [c.code for c in active_currencies()]


def get_currency(code: str) -> Currency | None:
    return Currency.objects.filter(code=code.upper()).first()


def _latest_rates_from_db(base: str) -> dict[str, Decimal]:
    """Latest rate per quote for ``base`` (most recent fetched_at wins)."""
    rates: dict[str, Decimal] = {base: Decimal("1")}
    seen: set[str] = set()
    for row in ExchangeRate.objects.filter(base=base).order_by("quote", "-fetched_at"):
        if row.quote in seen:
            continue
        seen.add(row.quote)
        rates[row.quote] = row.rate
    return rates


def get_rates() -> dict[str, Decimal]:
    """Cached ``{code: Decimal}`` map (1 base = rate × code).

    Reads the cache first, falling back to the DB's last-good rows so a downed
    FX API or cold cache never blocks browsing/checkout.
    """
    base = base_code()
    try:
        cached = cache.get(RATES_CACHE_KEY)
    except Exception:  # noqa: BLE001
        cached = None
    if cached and cached.get("base") == base:
        return {code: Decimal(str(v)) for code, v in cached["rates"].items()}
    return _latest_rates_from_db(base)


def rates_status() -> dict[str, object]:
    """Freshness info for admins: when rates were last fetched and staleness."""
    from django.utils import timezone

    base = base_code()
    latest = ExchangeRate.objects.filter(base=base).order_by("-fetched_at").first()
    if latest is None:
        return {"fetched_at": None, "stale": True, "base": base}
    refresh_minutes = int(get_setting("currency.refresh_minutes"))
    age = timezone.now() - latest.fetched_at
    stale = age.total_seconds() > refresh_minutes * 60 * 2
    return {"fetched_at": latest.fetched_at, "stale": stale, "base": base, "source": latest.source}
