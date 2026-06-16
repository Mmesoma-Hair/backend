"""Notification delivery task (robust: retry with backoff, idempotent)."""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .channels.email import EmailDeliveryError, EmailMessage, get_email_backend
from .channels.telegram import TelegramDeliveryError, get_telegram_backend
from .models import Channel, Notification, NotificationStatus

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5, default_retry_delay=30, acks_late=True)
def deliver_notification(self, notification_id: str) -> str:  # type: ignore[no-untyped-def]
    note = Notification.objects.filter(id=notification_id).first()
    if note is None:
        return "missing"
    if note.status == NotificationStatus.SENT:
        return "already_sent"  # idempotent

    note.attempts += 1
    try:
        if note.channel == Channel.EMAIL:
            response = _send_email(note)
        else:
            response = _send_telegram(note)
    except (EmailDeliveryError, TelegramDeliveryError) as exc:
        note.status = NotificationStatus.FAILED
        note.error = str(exc)[:1000]
        note.save(update_fields=["status", "error", "attempts", "updated_at"])
        # Exponential backoff: 30s, 60s, 120s, ...
        raise self.retry(exc=exc, countdown=30 * (2**self.request.retries)) from exc
    except Exception as exc:  # noqa: BLE001 - unexpected; record and stop
        note.status = NotificationStatus.FAILED
        note.error = str(exc)[:1000]
        note.save(update_fields=["status", "error", "attempts", "updated_at"])
        logger.exception("Notification %s delivery errored", notification_id)
        return "failed"

    note.status = NotificationStatus.SENT
    note.sent_at = timezone.now()
    note.provider_response = response if isinstance(response, dict) else {"response": str(response)}
    note.save(update_fields=["status", "sent_at", "provider_response", "attempts", "updated_at"])
    return "sent"


def _send_email(note: Notification) -> dict:
    from django.conf import settings

    backend = get_email_backend()
    return backend.send(
        EmailMessage(
            to=note.recipient,
            subject=note.subject,
            html=note.body_html,
            text=note.body_text,
            from_address=settings.EMAIL_FROM_ADDRESS,
            from_name=settings.EMAIL_FROM_NAME,
        )
    )


def _send_telegram(note: Notification) -> dict:
    # Prefer the target user's own bot token (their bot), else the store default.
    bot_token: str | None = None
    if note.user_id:
        profile = getattr(note.user, "profile", None)
        bot_token = getattr(profile, "telegram_bot_token", "") or None
    return get_telegram_backend().send(note.recipient, note.body_text, bot_token=bot_token)
