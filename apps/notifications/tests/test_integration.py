from __future__ import annotations

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.notifications.channels.email import MemoryEmailBackend
from apps.notifications.channels.telegram import MemoryTelegramBackend
from apps.notifications.models import Channel, Notification
from apps.orders import services as order_services
from apps.payments import services as payment_services
from apps.storeconfig import services as config_services


@pytest.fixture(autouse=True)
def _setup(db):
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")
    MemoryEmailBackend.outbox.clear()
    MemoryTelegramBackend.outbox.clear()
    yield


def test_welcome_email_on_registration() -> None:
    from apps.accounts import services as account_services
    from apps.notifications.notify import send_welcome

    user = account_services.register_user(email="new@example.com", password="Sup3rSecret!")
    send_welcome(user)
    assert any(m.to == "new@example.com" for m in MemoryEmailBackend.outbox)


def test_order_paid_emails_customer_and_alerts_ops() -> None:
    owner = UserFactory(email="owner@example.com", password="x")
    cart = cart_services.get_or_create_cart(user=owner)
    cart_services.add_item(cart, variant_id=str(make_variant("20.00").id), quantity=1)
    cart_services.set_shipping(cart, {"name": "O", "line1": "1", "city": "T", "country": "US"})
    order = order_services.checkout(cart, idempotency_key="notif-1", currency="USD")
    payment_services.confirm_mock_payment(order.payments.first())

    # Customer gets an order confirmation email.
    assert Notification.objects.filter(
        event="order_confirmation", channel=Channel.EMAIL, recipient="owner@example.com"
    ).exists()
    # Store ops get a Telegram alert (TELEGRAM_DEFAULT_CHAT_ID = "ops-chat" in test settings).
    assert any(chat == "ops-chat" for chat, _text, _token in MemoryTelegramBackend.outbox)
    # Shipping is now a deliberate admin action — no "shipped" email at payment.
    assert not Notification.objects.filter(event="shipment_update", channel=Channel.EMAIL).exists()

    # Once the admin marks the internal shipment shipped, the email goes out.
    from apps.fulfillment import services as fulfillment_services

    order.refresh_from_db()
    fulfillment_services.mark_internal_shipped(order, tracking_number="TRK9", carrier="UPS")
    assert Notification.objects.filter(
        event="shipment_update", channel=Channel.EMAIL, recipient="owner@example.com"
    ).exists()


def test_payer_also_notified_for_pay_for_a_friend() -> None:
    owner = UserFactory(email="owner2@example.com", password="x")
    cart = cart_services.get_or_create_cart(user=owner)
    cart_services.add_item(cart, variant_id=str(make_variant("15.00").id), quantity=1)
    cart_services.set_shipping(cart, {"name": "O", "line1": "1", "city": "T", "country": "US"})
    order = order_services.checkout(
        cart, idempotency_key="notif-2", currency="USD", payer_email="friend@example.com"
    )
    payment_services.confirm_mock_payment(order.payments.first())
    recipients = {m.to for m in MemoryEmailBackend.outbox}
    assert "owner2@example.com" in recipients
    assert "friend@example.com" in recipients
