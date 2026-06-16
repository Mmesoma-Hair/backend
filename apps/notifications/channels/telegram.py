"""Pluggable Telegram backends.

``HttpTelegramBackend`` calls the Bot API (`sendMessage`); ``console`` prints,
``memory`` records for tests, and ``disabled`` is a safe no-op when Telegram
isn't configured. ``send`` returns provider info on success or raises
:class:`TelegramDeliveryError`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import requests
from django.conf import settings


class TelegramDeliveryError(Exception):
    pass


class BaseTelegramBackend(ABC):
    name = "base"

    @abstractmethod
    def send(self, chat_id: str, text: str, *, bot_token: str | None = None) -> dict[str, Any]:
        """Send ``text`` to ``chat_id``.

        ``bot_token`` overrides the store-default bot (used for a user's own bot);
        when omitted, the configured default token is used.
        """


class DisabledTelegramBackend(BaseTelegramBackend):
    name = "disabled"

    def send(self, chat_id: str, text: str, *, bot_token: str | None = None) -> dict[str, Any]:
        return {"backend": "disabled", "delivered": False, "reason": "telegram_disabled"}


class ConsoleTelegramBackend(BaseTelegramBackend):
    name = "console"

    def send(self, chat_id: str, text: str, *, bot_token: str | None = None) -> dict[str, Any]:
        print(f"\n--- TELEGRAM ---\nChat: {chat_id}\n{text}\n----------------\n")
        return {"backend": "console", "delivered": True}


class MemoryTelegramBackend(BaseTelegramBackend):
    name = "memory"
    # Records (chat_id, text, bot_token) so tests can assert the per-user token.
    outbox: list[tuple[str, str, str | None]] = []
    fail_times: int = 0

    def send(self, chat_id: str, text: str, *, bot_token: str | None = None) -> dict[str, Any]:
        if MemoryTelegramBackend.fail_times > 0:
            MemoryTelegramBackend.fail_times -= 1
            raise TelegramDeliveryError("Simulated telegram failure.")
        MemoryTelegramBackend.outbox.append((chat_id, text, bot_token))
        return {"backend": "memory", "delivered": True}


class HttpTelegramBackend(BaseTelegramBackend):
    name = "http"

    def send(self, chat_id: str, text: str, *, bot_token: str | None = None) -> dict[str, Any]:
        token = bot_token or settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise TelegramDeliveryError("No Telegram bot token configured.")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=settings.NOTIFICATIONS_HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise TelegramDeliveryError(f"Telegram request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise TelegramDeliveryError(f"Telegram {resp.status_code}: {resp.text[:500]}")
        return resp.json()


_BACKENDS: dict[str, type[BaseTelegramBackend]] = {
    "disabled": DisabledTelegramBackend,
    "console": ConsoleTelegramBackend,
    "memory": MemoryTelegramBackend,
    "http": HttpTelegramBackend,
}


def get_telegram_backend() -> BaseTelegramBackend:
    name = getattr(settings, "NOTIFICATIONS_TELEGRAM_BACKEND", "console")
    return _BACKENDS.get(name, ConsoleTelegramBackend)()
