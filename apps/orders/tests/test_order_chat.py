"""Chat-to-order endpoint: builds a summary, records the lead, returns links."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.orders.models import OrderInquiry
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")
    config_services.set_setting("order_chat.enabled", True)
    config_services.set_setting("order_chat.telegram_url", "https://t.me/primestore")
    config_services.set_setting("order_chat.whatsapp_number", "2348012345678")
    config_services.set_setting("order_chat.phone_number", "+2348012345678")


@pytest.mark.django_db
def test_product_inquiry_returns_links_and_records_lead(setup) -> None:
    v = make_variant("25.00", stock=5, title="Hoodie")
    r = APIClient().post(
        "/api/v1/order-chat/",
        {
            "channel": "telegram",
            "context": "product",
            "variant": str(v.id),
            "quantity": 2,
            "customer_name": "Ada",
            "customer_phone": "0801",
        },
        format="json",
    )
    assert r.status_code == 200
    links = r.data["links"]
    assert links["telegram"].startswith("https://t.me/primestore")
    assert links["whatsapp"].startswith("https://wa.me/2348012345678")
    assert links["call"] == "tel:+2348012345678"
    assert "Hoodie" in r.data["message"]

    inquiry = OrderInquiry.objects.get()
    assert inquiry.channel == "telegram"
    assert inquiry.context == "product"
    assert inquiry.customer_name == "Ada"
    assert "Hoodie" in inquiry.summary


@pytest.mark.django_db
def test_cart_inquiry_summarises_cart(setup) -> None:
    user = UserFactory()
    cart = cart_services.get_or_create_cart(user=user, session_key="")
    v = make_variant("10.00", stock=5, title="Cap")
    cart_services.add_item(cart, variant_id=str(v.id), quantity=3)

    client = APIClient()
    client.force_authenticate(user=user)
    r = client.post(
        "/api/v1/order-chat/",
        {"channel": "whatsapp", "context": "cart"},
        format="json",
    )
    assert r.status_code == 200
    assert "Cap" in r.data["message"]
    assert OrderInquiry.objects.filter(context="cart").exists()


@pytest.mark.django_db
def test_product_inquiry_requires_variant(setup) -> None:
    r = APIClient().post(
        "/api/v1/order-chat/", {"channel": "telegram", "context": "product"}, format="json"
    )
    assert r.status_code == 400
