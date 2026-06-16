from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.cart import services
from apps.cart.models import Cart
from apps.common.exceptions import GoneError
from apps.storeconfig import services as config_services

from .factories import make_variant, setup_currencies


@pytest.fixture
def currencies(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _shared_cart() -> Cart:
    cart = services.get_or_create_cart(session_key="owner-sess")
    services.add_item(cart, variant_id=str(make_variant("10.00").id), quantity=2)
    services.create_share(cart)
    return cart


@pytest.mark.django_db
def test_create_share_generates_token(currencies: None) -> None:
    cart = _shared_cart()
    assert cart.share_token
    assert cart.is_shared


@pytest.mark.django_db
def test_resolve_shared_cart_ok(currencies: None) -> None:
    cart = _shared_cart()
    resolved = services.resolve_shared_cart(cart.share_token)
    assert resolved.id == cart.id


@pytest.mark.django_db
def test_revoked_share_raises_gone(currencies: None) -> None:
    cart = _shared_cart()
    services.revoke_share(cart)
    with pytest.raises(GoneError):
        services.resolve_shared_cart(cart.share_token)


@pytest.mark.django_db
def test_expired_share_raises_gone(currencies: None) -> None:
    cart = _shared_cart()
    Cart.objects.filter(pk=cart.pk).update(share_expires_at=timezone.now() - timedelta(hours=1))
    cart.refresh_from_db()
    with pytest.raises(GoneError):
        services.resolve_shared_cart(cart.share_token)


@pytest.mark.django_db
def test_shared_cart_endpoint_sanitized_and_410(currencies: None) -> None:
    client = APIClient()
    cart = _shared_cart()

    ok = client.get(reverse("api-v1:cart-shared", args=[cart.share_token]))
    assert ok.status_code == 200
    assert ok.data["subtotal"]["amount"] == "20.00"
    # No owner PII leaks into the shared payload.
    body = str(ok.data)
    assert "owner" not in ok.data
    assert "email" not in body

    services.revoke_share(cart)
    gone = client.get(reverse("api-v1:cart-shared", args=[cart.share_token]))
    assert gone.status_code == 410
    assert gone.data["error"]["code"] == "share_revoked"


@pytest.mark.django_db
def test_shared_cart_unknown_token_404(currencies: None) -> None:
    client = APIClient()
    resp = client.get(reverse("api-v1:cart-shared", args=["nope"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_share_disabled_by_feature_flag(currencies: None) -> None:
    config_services.set_setting("features.pay_for_a_friend", "false")
    cart = services.get_or_create_cart(session_key="x")
    from apps.common.exceptions import DomainError

    with pytest.raises(DomainError):
        services.create_share(cart)
    config_services.set_setting("features.pay_for_a_friend", "true")
