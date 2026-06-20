"""MOQ + quantity price breaks, and the product review system."""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.catalog.models import ProductReview
from apps.orders import services as order_services
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _tiered(price="100.00"):
    v = make_variant(price, stock=500, title="Bulk Tee")
    v.moq = 10
    v.price_tiers = [
        {"min_qty": 10, "price": "90.00"},
        {"min_qty": 50, "price": "80.00"},
    ]
    v.save()
    return v


@pytest.mark.django_db
def test_unit_price_for_applies_price_breaks(setup) -> None:
    v = _tiered()
    assert v.unit_price_for(1) == Decimal("100.00")
    assert v.unit_price_for(10) == Decimal("90.00")
    assert v.unit_price_for(49) == Decimal("90.00")
    assert v.unit_price_for(50) == Decimal("80.00")


@pytest.mark.django_db
def test_cart_enforces_moq(setup) -> None:
    v = _tiered()
    cart = cart_services.get_or_create_cart(user=None, session_key="s-moq")
    line = cart_services.add_item(cart, variant_id=str(v.id), quantity=1)
    assert line.quantity == 10  # bumped up to MOQ


@pytest.mark.django_db
def test_checkout_charges_tier_price(setup) -> None:
    v = _tiered()
    cart = cart_services.get_or_create_cart(user=None, session_key="s-tier")
    cart_services.add_item(cart, variant_id=str(v.id), quantity=50)
    order = order_services.checkout(cart, idempotency_key="moq-1", currency="USD")
    assert order.total_charged == Decimal("4000.00")  # 50 × 80


@pytest.mark.django_db
def test_submit_review_updates_aggregates_and_lists(setup) -> None:
    v = make_variant("20.00", title="Reviewed")
    product = v.product
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)

    r = client.post(
        "/api/v1/catalog/reviews/",
        {"product": str(product.id), "rating": 5, "title": "Great", "body": "Love it"},
        format="json",
    )
    assert r.status_code == 201
    assert r.data["is_verified_purchase"] is False

    product.refresh_from_db()
    assert product.rating_count == 1
    assert product.rating_avg == Decimal("5.00")

    listed = APIClient().get(f"/api/v1/catalog/products/{product.slug}/reviews/")
    assert listed.data["count"] == 1
    assert listed.data["results"][0]["title"] == "Great"


@pytest.mark.django_db
def test_one_review_per_user(setup) -> None:
    v = make_variant("20.00", title="Once")
    product = v.product
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    client.post(
        "/api/v1/catalog/reviews/",
        {"product": str(product.id), "rating": 4},
        format="json",
    )
    client.post(
        "/api/v1/catalog/reviews/",
        {"product": str(product.id), "rating": 2},
        format="json",
    )
    assert ProductReview.objects.filter(product=product, user=user).count() == 1
    product.refresh_from_db()
    assert product.rating_avg == Decimal("2.00")  # updated, not duplicated


@pytest.mark.django_db
def test_review_requires_auth(setup) -> None:
    v = make_variant("20.00", title="Auth")
    r = APIClient().post(
        "/api/v1/catalog/reviews/",
        {"product": str(v.product.id), "rating": 5},
        format="json",
    )
    assert r.status_code in (401, 403)


@pytest.mark.django_db
def test_price_tiers_must_decrease(setup) -> None:
    from apps.catalog.admin_serializers import VariantAdminSerializer

    v = make_variant("45000.00", title="Wholesale Hoodie")  # base price 45000

    # A break that costs MORE at a higher quantity is rejected (base from instance).
    bad = VariantAdminSerializer(
        instance=v,
        data={"price_tiers": [{"min_qty": 5, "price": "9000"}, {"min_qty": 11, "price": "9500"}]},
        partial=True,
    )
    assert not bad.is_valid()
    assert "price_tiers" in bad.errors

    # A break priced above the base is rejected.
    over = VariantAdminSerializer(
        instance=v,
        data={"price_tiers": [{"min_qty": 5, "price": "50000"}]},
        partial=True,
    )
    assert not over.is_valid()

    # Proper descending breaks are accepted.
    good = VariantAdminSerializer(
        instance=v,
        data={"price_tiers": [{"min_qty": 6, "price": "40000"}, {"min_qty": 20, "price": "35000"}]},
        partial=True,
    )
    assert good.is_valid(), good.errors


@pytest.mark.django_db
def test_storefront_hides_non_saving_tiers(setup) -> None:
    from apps.catalog.serializers import VariantSerializer

    v = make_variant("45000.00", title="Defensive")
    v.price_tiers = [
        {"min_qty": 5, "price": "10"},
        {"min_qty": 11, "price": "20"},  # not a saving vs the 5-tier — hidden
    ]
    v.save()
    data = VariantSerializer(v, context={"currency": "NGN"}).data
    mins = [t["min_qty"] for t in data["price_tiers"]]
    assert 11 not in mins
