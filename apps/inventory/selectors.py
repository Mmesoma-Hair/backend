"""Inventory read logic."""

from __future__ import annotations

from apps.catalog.models import Variant

from . import services


def variant_availability(variant: Variant) -> int:
    return services.available_quantity(variant)


def is_in_stock(variant: Variant, quantity: int = 1) -> bool:
    return services.available_quantity(variant) >= quantity
