from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.models import Product, Variant
from apps.inventory import services
from apps.inventory.models import Reservation, StockItem
from apps.inventory.services import InsufficientStock


def _variant(fulfillment: str = "internal") -> Variant:
    product = Product.objects.create(title="P", slug="p", fulfillment_type=fulfillment)
    return Variant.objects.create(product=product, sku="V1", price=Decimal("1"), is_default=True)


@pytest.mark.django_db
def test_set_stock_and_availability() -> None:
    v = _variant()
    services.set_stock(v, 10)
    assert services.available_quantity(v) == 10


@pytest.mark.django_db
def test_reserve_decrements_availability() -> None:
    v = _variant()
    services.set_stock(v, 10)
    res = services.reserve(v, 3, reference="cart:1")
    assert res.status == Reservation.Status.ACTIVE
    assert services.available_quantity(v) == 7
    item = StockItem.objects.get(variant=v)
    assert item.on_hand == 10 and item.reserved == 3


@pytest.mark.django_db
def test_reserve_insufficient_stock_raises() -> None:
    v = _variant()
    services.set_stock(v, 2)
    with pytest.raises(InsufficientStock):
        services.reserve(v, 5, reference="cart:1")
    assert services.available_quantity(v) == 2  # unchanged


@pytest.mark.django_db
def test_release_returns_stock() -> None:
    v = _variant()
    services.set_stock(v, 10)
    services.reserve(v, 4, reference="cart:9")
    assert services.available_quantity(v) == 6
    released = services.release("cart:9")
    assert released == 1
    assert services.available_quantity(v) == 10


@pytest.mark.django_db
def test_consume_removes_stock_permanently() -> None:
    v = _variant()
    services.set_stock(v, 10)
    services.reserve(v, 4, reference="order:1")
    services.consume("order:1")
    item = StockItem.objects.get(variant=v)
    assert item.on_hand == 6 and item.reserved == 0
    assert services.available_quantity(v) == 6


@pytest.mark.django_db
def test_dropship_variant_reserves_without_owned_stock() -> None:
    v = _variant(fulfillment="dropship")
    # No stock set; dropship availability is supplier-reported (effectively open).
    res = services.reserve(v, 100, reference="cart:1")
    assert res.status == Reservation.Status.ACTIVE
    assert res.warehouse_id is None


@pytest.mark.django_db
def test_release_expired_frees_old_reservations() -> None:
    v = _variant()
    services.set_stock(v, 10)
    res = services.reserve(v, 5, reference="cart:7", ttl_minutes=30)
    # Force expiry into the past.
    Reservation.objects.filter(pk=res.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    freed = services.release_expired()
    assert freed == 1
    assert services.available_quantity(v) == 10
