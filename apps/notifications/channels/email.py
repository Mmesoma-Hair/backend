"""Pluggable transactional-email backends.

The dispatch layer talks to a ``BaseEmailBackend``; the concrete provider is a
settings switch (``NOTIFICATIONS_EMAIL_BACKEND``). ``ZeptoMailBackend`` calls
Zoho's ZeptoMail HTTP API; ``console`` prints; ``memory`` records in-process for
tests; ``django`` uses Django's configured email backend.

A backend's ``send`` returns a provider response dict on success and raises
:class:`EmailDeliveryError` on failure, so the Celery task can retry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings


class EmailDeliveryError(Exception):
    """Raised when a backend fails to hand off the message (transient or fatal)."""


@dataclass
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str
    from_address: str = ""
    from_name: str = ""


class BaseEmailBackend(ABC):
    name = "base"

    @abstractmethod
    def send(self, message: EmailMessage) -> dict[str, Any]:
        """Deliver ``message``; return provider info or raise EmailDeliveryError."""


class ConsoleEmailBackend(BaseEmailBackend):
    name = "console"

    def send(self, message: EmailMessage) -> dict[str, Any]:
        print(
            f"\n--- EMAIL ---\nTo: {message.to}\nSubject: {message.subject}\n\n"
            f"{message.text}\n-------------\n"
        )
        return {"backend": "console", "delivered": True}


class MemoryEmailBackend(BaseEmailBackend):
    """In-process recorder for tests. Inspect via ``MemoryEmailBackend.outbox``."""

    name = "memory"
    outbox: list[EmailMessage] = []
    #: When set, the next N sends raise to exercise retry/failure handling.
    fail_times: int = 0

    def send(self, message: EmailMessage) -> dict[str, Any]:
        if MemoryEmailBackend.fail_times > 0:
            MemoryEmailBackend.fail_times -= 1
            raise EmailDeliveryError("Simulated email failure.")
        MemoryEmailBackend.outbox.append(message)
        return {"backend": "memory", "delivered": True}


class DjangoEmailBackend(BaseEmailBackend):
    """Use Django's configured EMAIL_BACKEND (e.g. SMTP, console in dev)."""

    name = "django"

    def send(self, message: EmailMessage) -> dict[str, Any]:
        from django.core.mail import EmailMultiAlternatives

        try:
            email = EmailMultiAlternatives(
                subject=message.subject,
                body=message.text,
                from_email=f"{message.from_name} <{message.from_address}>",
                to=[message.to],
            )
            if message.html:
                email.attach_alternative(message.html, "text/html")
            email.send(fail_silently=False)
        except Exception as exc:  # noqa: BLE001
            raise EmailDeliveryError(str(exc)) from exc
        return {"backend": "django", "delivered": True}


class ZeptoMailBackend(BaseEmailBackend):
    """Zoho ZeptoMail transactional email over HTTP."""

    name = "zeptomail"

    def send(self, message: EmailMessage) -> dict[str, Any]:
        token = settings.ZEPTOMAIL_TOKEN
        if not token:
            raise EmailDeliveryError("ZEPTOMAIL_TOKEN is not configured.")
        payload = {
            "from": {"address": message.from_address, "name": message.from_name},
            "to": [{"email_address": {"address": message.to, "name": message.to}}],
            "subject": message.subject,
            "htmlbody": message.html or message.text,
            "textbody": message.text,
        }
        try:
            resp = requests.post(
                settings.ZEPTOMAIL_API_URL,
                json=payload,
                headers={
                    "Authorization": token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=settings.NOTIFICATIONS_HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise EmailDeliveryError(f"ZeptoMail request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise EmailDeliveryError(f"ZeptoMail {resp.status_code}: {resp.text[:500]}")
        try:
            return resp.json()
        except ValueError:
            return {"status_code": resp.status_code}


_BACKENDS: dict[str, type[BaseEmailBackend]] = {
    "console": ConsoleEmailBackend,
    "memory": MemoryEmailBackend,
    "django": DjangoEmailBackend,
    "zeptomail": ZeptoMailBackend,
}


def get_email_backend() -> BaseEmailBackend:
    name = getattr(settings, "NOTIFICATIONS_EMAIL_BACKEND", "console")
    return _BACKENDS.get(name, ConsoleEmailBackend)()
