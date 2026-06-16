from __future__ import annotations

from unittest import mock

import pytest

from apps.notifications.channels.email import (
    EmailDeliveryError,
    EmailMessage,
    ZeptoMailBackend,
)
from apps.notifications.channels.telegram import HttpTelegramBackend, TelegramDeliveryError


def _msg() -> EmailMessage:
    return EmailMessage(
        to="a@b.com",
        subject="Hi",
        html="<p>Hi</p>",
        text="Hi",
        from_address="no-reply@store.test",
        from_name="Store",
    )


def test_zeptomail_posts_to_api(settings) -> None:
    settings.ZEPTOMAIL_TOKEN = "Zoho-enczapikey TESTTOKEN"
    settings.ZEPTOMAIL_API_URL = "https://api.zeptomail.com/v1.1/email"
    with mock.patch("apps.notifications.channels.email.requests.post") as post:
        post.return_value = mock.Mock(status_code=201, json=lambda: {"data": "ok"})
        result = ZeptoMailBackend().send(_msg())
    assert result == {"data": "ok"}
    args, kwargs = post.call_args
    assert kwargs["json"]["to"][0]["email_address"]["address"] == "a@b.com"
    assert kwargs["headers"]["Authorization"] == "Zoho-enczapikey TESTTOKEN"


def test_zeptomail_missing_token_raises(settings) -> None:
    settings.ZEPTOMAIL_TOKEN = ""
    with pytest.raises(EmailDeliveryError):
        ZeptoMailBackend().send(_msg())


def test_zeptomail_http_error_raises(settings) -> None:
    settings.ZEPTOMAIL_TOKEN = "tok"
    with mock.patch("apps.notifications.channels.email.requests.post") as post:
        post.return_value = mock.Mock(status_code=400, text="bad request")
        with pytest.raises(EmailDeliveryError):
            ZeptoMailBackend().send(_msg())


def test_telegram_http_sends(settings) -> None:
    settings.TELEGRAM_BOT_TOKEN = "123:abc"
    with mock.patch("apps.notifications.channels.telegram.requests.post") as post:
        post.return_value = mock.Mock(status_code=200, json=lambda: {"ok": True})
        result = HttpTelegramBackend().send("chat-1", "<b>Hi</b>")
    assert result == {"ok": True}
    args, kwargs = post.call_args
    assert "123:abc" in args[0]
    assert kwargs["json"]["chat_id"] == "chat-1"


def test_telegram_missing_token_raises(settings) -> None:
    settings.TELEGRAM_BOT_TOKEN = ""
    with pytest.raises(TelegramDeliveryError):
        HttpTelegramBackend().send("chat", "hi")
