from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.orders.models import Order, OrderStatus
from apps.payments import services as payment_services
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _owner_shared_cart():
    owner = UserFactory(email="owner@example.com", password="Pass12345!")
    cart = cart_services.get_or_create_cart(user=owner)
    v = make_variant("30.00", stock=10)
    cart_services.add_item(cart, variant_id=str(v.id), quantity=1)
    cart_services.set_shipping(
        cart, {"name": "Owner", "line1": "1 St", "city": "Town", "country": "US"}
    )
    cart_services.create_share(cart)
    return owner, cart


@pytest.mark.django_db
def test_different_user_pays_shared_cart_owner_keeps_ownership(setup) -> None:
    owner, cart = _owner_shared_cart()
    payer = UserFactory(email="payer@example.com", password="Pass12345!")

    client = APIClient()
    client.force_authenticate(payer)
    resp = client.post(
        f"/api/v1/checkout/shared/{cart.share_token}/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="friend-1",
    )
    assert resp.status_code == 201
    order = Order.objects.get(number=resp.data["number"])
    assert order.owner_id == owner.id  # ownership stays with the cart owner
    assert order.paid_by_user_id == payer.id  # payer recorded separately

    # The payer can complete payment → order paid (auto-routes to a pending
    # internal shipment → "processing"), still owned by the owner.
    payment_services.confirm_mock_payment(order.payments.first())
    order.refresh_from_db()
    assert order.paid_at is not None
    assert order.status == OrderStatus.ROUTING
    assert order.owner_id == owner.id
    assert order.paid_by_user_id == payer.id


@pytest.mark.django_db
def test_guest_pays_shared_cart(setup) -> None:
    owner, cart = _owner_shared_cart()
    client = APIClient()  # anonymous guest
    resp = client.post(
        f"/api/v1/checkout/shared/{cart.share_token}/",
        {"payer": {"email": "guest@example.com", "name": "Guest"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="guest-1",
    )
    assert resp.status_code == 201
    order = Order.objects.get(number=resp.data["number"])
    assert order.owner_id == owner.id
    assert order.paid_by_user_id is None
    assert order.payer_email == "guest@example.com"


@pytest.mark.django_db
def test_guest_payer_requires_email(setup) -> None:
    owner, cart = _owner_shared_cart()
    client = APIClient()
    resp = client.post(
        f"/api/v1/checkout/shared/{cart.share_token}/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="guest-2",
    )
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "payer_required"


@pytest.mark.django_db
def test_checkout_requires_idempotency_key(setup) -> None:
    owner, cart = _owner_shared_cart()
    client = APIClient()
    resp = client.post(
        f"/api/v1/checkout/shared/{cart.share_token}/",
        {"payer": {"email": "g@example.com"}},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "idempotency_required"


@pytest.mark.django_db
def test_shared_checkout_endpoint_idempotent_retry(setup) -> None:
    owner, cart = _owner_shared_cart()
    client = APIClient()
    body = {"payer": {"email": "g@example.com"}}
    first = client.post(
        f"/api/v1/checkout/shared/{cart.share_token}/",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="retry-1",
    )
    # The cart is consumed after the first checkout; a retry with the same key
    # must return the same order rather than erroring on an empty cart.
    second = client.post(
        f"/api/v1/checkout/shared/{cart.share_token}/",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="retry-1",
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.data["number"] == second.data["number"]
    assert Order.objects.count() == 1


@pytest.mark.django_db
def test_revoked_share_cannot_be_paid(setup) -> None:
    owner, cart = _owner_shared_cart()
    cart_services.revoke_share(cart)
    client = APIClient()
    resp = client.post(
        f"/api/v1/checkout/shared/{cart.share_token}/",
        {"payer": {"email": "g@example.com"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="revoked-1",
    )
    assert resp.status_code == 410
