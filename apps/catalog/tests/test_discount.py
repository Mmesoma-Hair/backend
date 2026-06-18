"""Product-level discount: effective pricing, checkout charge, serializer output."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.catalog.serializers import VariantSerializer
from apps.orders import services as order_services
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _discount(variant, percent: str) -> None:
    variant.product.discount_percent = Decimal(percent)
    variant.product.save(update_fields=["discount_percent"])


@pytest.mark.django_db
def test_effective_price_applies_discount(setup) -> None:
    v = make_variant("100.00")
    _discount(v, "25")
    v.refresh_from_db()
    assert v.effective_price == Decimal("75.00")
    assert v.is_discounted is True


@pytest.mark.django_db
def test_checkout_charges_discounted_price(setup) -> None:
    v = make_variant("100.00", stock=5)
    _discount(v, "20")
    cart = cart_services.get_or_create_cart(user=None, session_key="s-disc")
    cart_services.add_item(cart, variant_id=str(v.id), quantity=2)

    order = order_services.checkout(cart, idempotency_key="disc-1", currency="USD")
    # 2 × (100 − 20%) = 2 × 80 = 160
    assert order.total_charged == Decimal("160.00")


@pytest.mark.django_db
def test_serializer_exposes_compare_at_and_discount(setup) -> None:
    v = make_variant("50.00")
    _discount(v, "10")
    v.refresh_from_db()
    data = VariantSerializer(v, context={"currency": "USD"}).data
    assert Decimal(data["price"]) == Decimal("45.00")  # effective
    assert Decimal(str(data["discount_percent"])) == Decimal("10.00")
    assert data["compare_at_display"] is not None  # original, struck-through
    assert data["price_display"] is not None


@pytest.mark.django_db
def test_no_discount_has_no_compare_at(setup) -> None:
    v = make_variant("50.00")
    data = VariantSerializer(v, context={"currency": "USD"}).data
    assert Decimal(data["price"]) == Decimal("50.00")
    assert data["compare_at_display"] is None
