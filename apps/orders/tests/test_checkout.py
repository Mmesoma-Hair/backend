from __future__ import annotations

from decimal import Decimal

import pytest

from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.inventory.services import available_quantity
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus
from apps.payments import services as payment_services
from apps.payments.models import Payment
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _cart_with_item(session="s1", price="20.00", qty=1, owner=None):
    cart = cart_services.get_or_create_cart(user=owner, session_key="" if owner else session)
    v = make_variant(price, stock=10)
    cart_services.add_item(cart, variant_id=str(v.id), quantity=qty)
    cart_services.set_shipping(
        cart, {"name": "Owner", "line1": "1 St", "city": "Town", "country": "US"}
    )
    return cart, v


@pytest.mark.django_db
def test_checkout_creates_pending_order_and_reserves_stock(setup) -> None:
    cart, v = _cart_with_item(price="20.00", qty=2)
    order = order_services.checkout(cart, idempotency_key="key-1", currency="USD")
    assert order.status == OrderStatus.PENDING
    assert order.total_charged == Decimal("40.00")
    assert order.lines.count() == 1
    # Stock reserved for the order.
    assert available_quantity(v) == 8
    # A pending payment intent exists.
    assert Payment.objects.filter(order=order, status=Payment.Status.PENDING).exists()


@pytest.mark.django_db
def test_checkout_is_idempotent(setup) -> None:
    cart, _ = _cart_with_item()
    o1 = order_services.checkout(cart, idempotency_key="same", currency="USD")
    o2 = order_services.checkout(cart, idempotency_key="same", currency="USD")
    assert o1.id == o2.id
    assert Order.objects.count() == 1


@pytest.mark.django_db
def test_checkout_locks_fx_rate_and_charges_in_currency(setup) -> None:
    cart, _ = _cart_with_item(price="100.00", qty=1)
    order = order_services.checkout(cart, idempotency_key="fx", currency="EUR")
    # 100 * 0.92 = 92.00 at the locked rate.
    assert order.fx_rate_locked == Decimal("0.9200000000")
    assert order.total_charged == Decimal("92.00")
    assert order.total_base == Decimal("100.00")


@pytest.mark.django_db
def test_mock_payment_drives_order_to_paid(setup) -> None:
    cart, _ = _cart_with_item()
    order = order_services.checkout(cart, idempotency_key="pay", currency="USD")
    payment = order.payments.first()
    payment_services.confirm_mock_payment(payment)
    order.refresh_from_db()
    payment.refresh_from_db()
    # Payment succeeds and the order is marked paid; an internal-only order then
    # auto-routes and ships, so the terminal status here is FULFILLED.
    assert order.paid_at is not None
    assert order.status == OrderStatus.FULFILLED
    assert payment.status == Payment.Status.SUCCEEDED


@pytest.mark.django_db
def test_webhook_idempotency(setup) -> None:
    cart, _ = _cart_with_item()
    order = order_services.checkout(cart, idempotency_key="wh", currency="USD")
    payment = order.payments.first()
    from apps.payments.providers import get_payment_provider

    provider = get_payment_provider()
    body, sig = provider.build_event(intent_id=payment.intent_id, status="succeeded")

    first = payment_services.process_webhook(provider_name="mock", payload=body, signature=sig)
    second = payment_services.process_webhook(provider_name="mock", payload=body, signature=sig)
    assert first["status"] == "applied"
    assert second["status"] == "duplicate"


@pytest.mark.django_db
def test_webhook_bad_signature_rejected(setup) -> None:
    cart, _ = _cart_with_item()
    order = order_services.checkout(cart, idempotency_key="bad", currency="USD")
    payment = order.payments.first()
    from apps.payments.providers import get_payment_provider
    from apps.payments.services import WebhookSignatureError

    body, _ = get_payment_provider().build_event(intent_id=payment.intent_id)
    with pytest.raises(WebhookSignatureError):
        payment_services.process_webhook(provider_name="mock", payload=body, signature="deadbeef")
