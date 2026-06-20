"""Storefront stock-bar baseline and flash-sale grouping."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.cart.tests.factories import make_variant
from apps.catalog import selectors
from apps.inventory import services as inv


@pytest.mark.django_db
def test_full_stock_is_high_water_mark() -> None:
    v = make_variant("10.00", title="Bar")
    item = inv.set_stock(v, 100)
    assert (item.on_hand, item.full_stock) == (100, 100)

    item = inv.set_stock(v, 40)  # sold down / corrected — baseline holds
    assert (item.on_hand, item.full_stock) == (40, 100)

    item = inv.set_stock(v, 150)  # restock above prior peak raises baseline
    assert (item.on_hand, item.full_stock) == (150, 150)


@pytest.mark.django_db
def test_product_stock_depletes_with_reservations() -> None:
    v = make_variant("10.00", title="Deplete")
    inv.set_stock(v, 100)
    inv.reserve(v, 30, reference="cart:1")

    available, full = selectors.product_stock(v.product)
    assert (available, full) == (70, 100)


@pytest.mark.django_db
def test_list_exposes_stock_and_flash_fields() -> None:
    v = make_variant("10.00", title="Listed")
    inv.set_stock(v, 80)
    inv.reserve(v, 5, reference="cart:2")

    res = APIClient().get("/api/v1/catalog/products/?currency=NGN")
    row = next(r for r in res.data["results"] if r["slug"] == v.product.slug)
    assert row["stock_available"] == 75
    assert row["stock_full"] == 80
    assert row["is_flash_sale"] is False


@pytest.mark.django_db
def test_flash_sale_filter() -> None:
    flash = make_variant("10.00", title="Flash deal").product
    flash.is_flash_sale = True
    flash.save(update_fields=["is_flash_sale"])
    make_variant("10.00", title="Regular")

    res = APIClient().get("/api/v1/catalog/products/?is_flash_sale=true")
    slugs = [r["slug"] for r in res.data["results"]]
    assert flash.slug in slugs
    assert all(r["is_flash_sale"] for r in res.data["results"])
