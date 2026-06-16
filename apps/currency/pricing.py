"""Helpers for embedding currency-aware prices in storefront responses.

A serializer reads the requested display currency from its context (set by the
view from the ``currency`` query param, defaulting to the base) and turns a
base-currency amount into a :func:`apps.currency.services.price_quote` dict.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import selectors, services


def resolve_currency(requested: str | None) -> str:
    """Validate a requested code against active currencies; fall back to base."""
    base = selectors.base_code()
    if not requested:
        return base
    requested = requested.upper()
    return requested if requested in set(selectors.active_codes()) else base


def price_for(base_amount: Decimal | str | None, currency_code: str) -> dict[str, Any] | None:
    if base_amount is None:
        return None
    return services.price_quote(Decimal(str(base_amount)), currency_code)
