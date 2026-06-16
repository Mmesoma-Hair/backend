from __future__ import annotations

from decimal import Decimal

from apps.currency.models import Currency


def seed_basic_currencies() -> None:
    """USD base + EUR + GBP, with a charm-priced NGN for rounding tests."""
    Currency.objects.update_or_create(
        code="USD", defaults={"name": "US Dollar", "symbol": "$", "position": 0}
    )
    Currency.objects.update_or_create(
        code="EUR", defaults={"name": "Euro", "symbol": "€", "position": 1}
    )
    Currency.objects.update_or_create(
        code="GBP", defaults={"name": "British Pound", "symbol": "£", "position": 2}
    )
    Currency.objects.update_or_create(
        code="NGN",
        defaults={
            "name": "Naira",
            "symbol": "₦",
            "decimal_places": 2,
            "rounding_increment": Decimal("1"),
            "charm_pricing": True,
            "position": 3,
        },
    )
