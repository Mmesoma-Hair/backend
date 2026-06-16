from __future__ import annotations

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.notifications.channels.telegram import MemoryTelegramBackend
from apps.notifications.models import Channel, Notification
from apps.orders import services as order_services
from apps.payments import services as payment_services
from apps.storeconfig import services as config_services


@pytest.fixture(autouse=True)
def _setup(db):
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")
    yield


def _paid_order(owner):
    cart = cart_services.get_or_create_cart(user=owner)
    cart_services.add_item(cart, variant_id=str(make_variant("20.00").id), quantity=1)
    cart_services.set_shipping(cart, {"name": "O", "line1": "1", "city": "T", "country": "US"})
    order = order_services.checkout(cart, idempotency_key=f"pref-{owner.id}", currency="USD")
    payment_services.confirm_mock_payment(order.payments.first())
    return order


@pytest.mark.django_db
def test_email_toggle_off_suppresses_user_email() -> None:
    owner = UserFactory(email="noemail@example.com", password="x")
    owner.profile.notify_email = False
    owner.profile.save()
    _paid_order(owner)
    # No order_confirmation email to the owner who disabled email.
    assert not Notification.objects.filter(
        event="order_confirmation", channel=Channel.EMAIL, recipient="noemail@example.com"
    ).exists()


@pytest.mark.django_db
def test_telegram_opt_in_uses_user_bot_token() -> None:
    owner = UserFactory(email="tg@example.com", password="x")
    owner.profile.notify_telegram = True
    owner.profile.telegram_chat_id = "my-chat"
    owner.profile.telegram_bot_token = "my-bot-token"
    owner.profile.save()
    _paid_order(owner)

    # Telegram order confirmation delivered to the user's chat using *their* token.
    assert any(
        chat == "my-chat" and token == "my-bot-token"
        for chat, _text, token in MemoryTelegramBackend.outbox
    )
    note = Notification.objects.get(
        event="order_confirmation", channel=Channel.TELEGRAM, recipient="my-chat"
    )
    assert note.user_id == owner.id


@pytest.mark.django_db
def test_telegram_not_sent_without_token() -> None:
    owner = UserFactory(email="tg2@example.com", password="x")
    owner.profile.notify_telegram = True
    owner.profile.telegram_chat_id = "chat-only"  # no bot token configured
    owner.profile.save()
    _paid_order(owner)
    # Not "connected" (missing token) → no telegram notification.
    assert not Notification.objects.filter(channel=Channel.TELEGRAM, recipient="chat-only").exists()
