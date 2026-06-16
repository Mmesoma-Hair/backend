from __future__ import annotations

from decimal import Decimal

from apps.catalog.models import Product, Variant
from apps.currency import services as currency_services
from apps.currency.tests.factories import seed_basic_currencies
from apps.inventory.services import set_stock


def setup_currencies() -> None:
    seed_basic_currencies()
    currency_services.refresh_rates()


def make_variant(price: str = "10.00", stock: int = 10, *, title: str = "Item") -> Variant:
    product = Product.objects.create(title=title)
    variant = Variant.objects.create(
        product=product,
        sku=f"{title.upper()[:6]}-{Variant.objects.count() + 1}",
        price=Decimal(price),
        is_default=True,
    )
    set_stock(variant, stock)
    return variant
