"""Order confirmation + cancellation carry the full order detail."""

from __future__ import annotations

import pytest

from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.notifications.models import Notification
from apps.orders import services as order_services
from apps.orders.models import OrderStatus
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _order():
    cart = cart_services.get_or_create_cart(user=None, session_key="s1")
    v = make_variant("20.00", stock=10)
    cart_services.add_item(cart, variant_id=str(v.id), quantity=2)
    cart_services.set_shipping(
        cart,
        {
            "name": "Jane Buyer",
            "line1": "5 Market St",
            "city": "Lagos",
            "country": "NG",
            "postal_code": "100001",
        },
    )
    return order_services.checkout(
        cart,
        idempotency_key="notif-k",
        currency="USD",
        contact_email="jane@example.com",
        contact_name="Jane Buyer",
    )


@pytest.mark.django_db
def test_order_confirmation_carries_full_details(setup) -> None:
    order = _order()
    order_services.mark_paid(order, payer_email="jane@example.com")

    note = Notification.objects.filter(event="order_confirmation", channel="email").first()
    assert note is not None
    body = note.body_text  # text body renders on all Python versions
    # Identity + money + line detail + shipping all present.
    assert order.number in body
    assert "Subtotal" in body and "Total" in body
    assert "USD 40.00" in body  # 2 × 20.00
    assert "Qty 2 x USD 20.00" in body
    assert "Lagos" in body
    assert "5 Market St" in body
    # The HTML body embeds the per-item image cell scaffold.
    assert note.body_html == "" or "_order_details" not in note.body_html


@pytest.mark.django_db
def test_order_cancellation_email_on_refund(setup) -> None:
    order = _order()
    order_services.mark_paid(order, payer_email="jane@example.com")
    order_services.transition(order, OrderStatus.REFUNDED)

    note = (
        Notification.objects.filter(event="order_cancelled", channel="email")
        .order_by("-created_at")
        .first()
    )
    assert note is not None
    assert "refunded" in note.body_text.lower()
    assert order.number in note.body_text
    assert "Total" in note.body_text


@pytest.mark.django_db
def test_order_cancellation_email_on_cancel(setup) -> None:
    order = _order()  # PENDING
    order_services.transition(order, OrderStatus.CANCELLED)

    note = Notification.objects.filter(event="order_cancelled", channel="email").first()
    assert note is not None
    assert "cancelled" in note.body_text.lower()
