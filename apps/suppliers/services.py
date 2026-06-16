"""Supplier sync logic: pull availability/prices via the adapter."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.catalog.models import Variant

from .adapters import get_adapter
from .models import Supplier, SupplierStock


@transaction.atomic
def sync_inventory(supplier: Supplier) -> int:
    """Pull supplier-reported availability into ``SupplierStock``. Returns rows synced."""
    data = get_adapter(supplier).fetch_inventory()
    for sku, qty in data.items():
        SupplierStock.objects.update_or_create(
            supplier=supplier, sku=sku, defaults={"available": max(int(qty), 0)}
        )
    return len(data)


@transaction.atomic
def sync_prices(supplier: Supplier) -> int:
    """Pull supplier prices and apply them to that supplier's dropship variants."""
    prices = get_adapter(supplier).fetch_prices()
    updated = 0
    for sku, price in prices.items():
        updated += Variant.objects.filter(sku=sku, supplier=supplier).update(
            price=Decimal(str(price))
        )
    return updated
