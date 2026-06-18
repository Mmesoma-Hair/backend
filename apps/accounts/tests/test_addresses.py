"""Address book: API CRUD + default handling, and checkout integration."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.accounts.tests.factories import UserFactory
from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.orders import services as order_services
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _auth_client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


_ADDR = {
    "name": "Ada Lovelace",
    "line1": "1 Analytical Way",
    "city": "London",
    "country": "GB",
}


@pytest.mark.django_db
def test_first_address_becomes_default(setup) -> None:
    user = UserFactory()
    client = _auth_client(user)
    r = client.post("/api/v1/auth/addresses/", _ADDR, format="json")
    assert r.status_code == 201
    assert r.data["is_default"] is True


@pytest.mark.django_db
def test_only_one_default_address(setup) -> None:
    user = UserFactory()
    client = _auth_client(user)
    client.post("/api/v1/auth/addresses/", _ADDR, format="json")
    r2 = client.post(
        "/api/v1/auth/addresses/",
        {**_ADDR, "label": "Office", "is_default": True},
        format="json",
    )
    assert r2.status_code == 201
    defaults = Address.objects.filter(user=user, is_default=True)
    assert defaults.count() == 1
    assert str(defaults.first().id) == r2.data["id"]


@pytest.mark.django_db
def test_addresses_are_scoped_to_user(setup) -> None:
    owner, other = UserFactory(), UserFactory()
    Address.objects.create(user=other, **_ADDR)
    r = _auth_client(owner).get("/api/v1/auth/addresses/")
    assert r.status_code == 200
    assert r.data["count"] == 0


@pytest.mark.django_db
def test_checkout_with_saved_address_id(setup) -> None:
    user = UserFactory()
    address = Address.objects.create(user=user, **_ADDR, is_default=True)
    cart = cart_services.get_or_create_cart(user=user, session_key="")
    v = make_variant("20.00", stock=5)
    cart_services.add_item(cart, variant_id=str(v.id), quantity=1)

    order = order_services.checkout(
        cart, idempotency_key="k1", currency="USD", owner_user=user, address_id=address.id
    )
    assert order.ship_line1 == "1 Analytical Way"
    assert order.ship_country == "GB"


@pytest.mark.django_db
def test_checkout_save_address_persists_to_book(setup) -> None:
    user = UserFactory()
    cart = cart_services.get_or_create_cart(user=user, session_key="")
    v = make_variant("20.00", stock=5)
    cart_services.add_item(cart, variant_id=str(v.id), quantity=1)

    order_services.checkout(
        cart,
        idempotency_key="k2",
        currency="USD",
        owner_user=user,
        shipping={"name": "Ada", "line1": "9 New Rd", "city": "Leeds", "country": "GB"},
        save_address=True,
    )
    saved = Address.objects.filter(user=user)
    assert saved.count() == 1
    assert saved.first().line1 == "9 New Rd"
    assert saved.first().is_default is True
