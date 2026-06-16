"""Seed default currencies and an initial set of exchange rates.

    uv run python manage.py seed_currencies

Creates USD (base), EUR, GBP, NGN and fetches an initial rate set via the
configured provider (mock by default), so the storefront can price in multiple
currencies immediately.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand

from apps.currency import services
from apps.currency.models import Currency

DEFAULTS = [
    {"code": "USD", "name": "US Dollar", "symbol": "$", "position": 0},
    {"code": "EUR", "name": "Euro", "symbol": "€", "position": 1},
    {"code": "GBP", "name": "British Pound", "symbol": "£", "position": 2},
    {
        "code": "NGN",
        "name": "Nigerian Naira",
        "symbol": "₦",
        "position": 3,
        "rounding_increment": Decimal("1"),
    },
]


class Command(BaseCommand):
    help = "Seed default currencies and initial exchange rates."

    def handle(self, *args: Any, **options: Any) -> None:
        for spec in DEFAULTS:
            Currency.objects.update_or_create(code=spec["code"], defaults=spec)
        result = services.refresh_rates()
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {len(DEFAULTS)} currencies; rate refresh: {result}")
        )
