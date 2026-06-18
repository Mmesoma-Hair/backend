"""Supplier sync logic: pull availability/prices via the adapter, apply markup."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q

from apps.catalog.models import Variant

from .adapters import get_adapter
from .models import Supplier, SupplierStock

_CENTS = Decimal("0.01")


def _supplier_variants(supplier: Supplier) -> Q:
    """Variants whose *effective* supplier is this one (direct or via product)."""
    return Q(supplier=supplier) | Q(supplier__isnull=True, product__supplier=supplier)


def sell_price(cost: Decimal, markup_percent: Decimal) -> Decimal:
    """Selling price = cost + the supplier's markup, rounded to 2dp (base currency).

    Per-display-currency rounding/charm pricing is applied later by the currency
    module; here we just store a clean base price that protects the margin.
    """
    cost = Decimal(str(cost or 0))
    markup = Decimal(str(markup_percent or 0))
    return (cost * (Decimal("1") + markup / Decimal("100"))).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )


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
    """Pull supplier COST prices, store them, and set the SELLING price = cost + markup.

    This is the core dropshipping mechanic: the catalog price the shopper sees
    always covers the supplier cost plus the configured profit margin.
    """
    prices = get_adapter(supplier).fetch_prices()
    updated = 0
    for sku, cost in prices.items():
        cost_dec = Decimal(str(cost))
        updated += Variant.objects.filter(_supplier_variants(supplier), sku=sku).update(
            cost_price=cost_dec,
            price=sell_price(cost_dec, supplier.markup_percent),
        )
    return updated


@transaction.atomic
def recompute_prices(supplier: Supplier) -> int:
    """Re-apply the supplier's markup to every dropship variant with a cost.

    Called when the markup changes so all selling prices update at once.
    """
    updated = 0
    for variant in Variant.objects.filter(_supplier_variants(supplier)).exclude(cost_price=0):
        variant.price = sell_price(variant.cost_price, supplier.markup_percent)
        variant.save(update_fields=["price", "updated_at"])
        updated += 1
    return updated
