from __future__ import annotations

from decimal import Decimal

import pytest

from apps.cart import selectors, services
from apps.cart.models import Cart
from apps.common.exceptions import DomainError
from apps.promotions.models import Coupon
from apps.storeconfig import services as config_services

from .factories import make_variant, setup_currencies


@pytest.fixture
def currencies(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _guest_cart() -> Cart:
    return services.get_or_create_cart(session_key="sess-123")


@pytest.mark.django_db
def test_add_update_remove_items(currencies: None) -> None:
    cart = _guest_cart()
    v = make_variant("10.00", stock=10)
    services.add_item(cart, variant_id=str(v.id), quantity=2)
    assert cart.lines.count() == 1
    line = cart.lines.first()
    assert line.quantity == 2

    services.update_item(cart, line_id=str(line.id), quantity=5)
    line.refresh_from_db()
    assert line.quantity == 5

    services.update_item(cart, line_id=str(line.id), quantity=0)  # removes
    assert cart.lines.count() == 0


@pytest.mark.django_db
def test_add_same_variant_merges(currencies: None) -> None:
    cart = _guest_cart()
    v = make_variant("10.00")
    services.add_item(cart, variant_id=str(v.id), quantity=1)
    services.add_item(cart, variant_id=str(v.id), quantity=2)
    assert cart.lines.count() == 1
    assert cart.lines.first().quantity == 3


@pytest.mark.django_db
def test_totals_currency_aware(currencies: None) -> None:
    cart = _guest_cart()
    services.add_item(cart, variant_id=str(make_variant("10.00").id), quantity=2)
    usd = selectors.compute_cart_totals(cart, currency="USD")
    eur = selectors.compute_cart_totals(cart, currency="EUR")
    assert usd["subtotal"]["amount"] == "20.00"
    assert eur["subtotal"]["amount"] == "18.40"  # 20 * 0.92


@pytest.mark.django_db
def test_totals_with_percentage_coupon(currencies: None) -> None:
    cart = _guest_cart()
    services.add_item(cart, variant_id=str(make_variant("100.00").id), quantity=1)
    Coupon.objects.create(
        code="P10", discount_type=Coupon.DiscountType.PERCENTAGE, value=Decimal("10")
    )
    services.apply_coupon(cart, code="P10")
    totals = selectors.compute_cart_totals(cart, currency="USD")
    assert totals["discounts"]["total"]["amount"] == "10.00"
    assert totals["total"]["amount"] == "90.00"


@pytest.mark.django_db
def test_validate_cart_flags_insufficient_stock(currencies: None) -> None:
    cart = _guest_cart()
    v = make_variant("10.00", stock=1)
    services.add_item(cart, variant_id=str(v.id), quantity=1)
    line = cart.lines.first()
    line.quantity = 5  # exceed stock
    line.save()
    issues = selectors.validate_cart(cart)
    assert any(i["code"] == "insufficient_stock" for i in issues)


@pytest.mark.django_db
def test_validate_cart_flags_price_change(currencies: None) -> None:
    cart = _guest_cart()
    v = make_variant("10.00")
    services.add_item(cart, variant_id=str(v.id), quantity=1)
    v.price = Decimal("12.00")
    v.save(update_fields=["price"])
    issues = selectors.validate_cart(cart)
    assert any(i["code"] == "price_changed" for i in issues)


@pytest.mark.django_db
def test_add_inactive_variant_rejected(currencies: None) -> None:
    cart = _guest_cart()
    v = make_variant("10.00")
    v.is_active = False
    v.save(update_fields=["is_active"])
    with pytest.raises(DomainError):
        services.add_item(cart, variant_id=str(v.id), quantity=1)
