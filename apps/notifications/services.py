"""Notification dispatch — the robust, provider-agnostic orchestration layer.

``dispatch`` renders a notification and persists one :class:`Notification` row
per channel/recipient, then enqueues delivery. Guarantees:

* **Idempotent** — a ``dedupe_key`` ensures the same event isn't re-sent to the
  same recipient/channel (safe to call from retried code paths).
* **Isolated** — each channel is handled independently; one failing never blocks
  another, and never raises back into the caller's business logic.
* **Retryable** — delivery runs in a Celery task with exponential backoff.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.storeconfig.selectors import get_setting

from . import events
from .models import Channel, Notification, NotificationStatus

logger = logging.getLogger(__name__)


def base_context() -> dict[str, Any]:
    """Branding/context every template can rely on."""
    return {
        "store_name": get_setting("store.name", "Eandewigs"),
        "support_email": get_setting("store.support_email", settings.SUPPORT_EMAIL),
        "logo_url": settings.EMAIL_LOGO_URL,
        "frontend_url": settings.FRONTEND_BASE_URL.rstrip("/"),
    }


def _enqueue_delivery(notification_id: str) -> None:
    from .tasks import deliver_notification

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        deliver_notification(notification_id)
    else:
        transaction.on_commit(lambda: deliver_notification.delay(notification_id))


def _ensure(
    channel: str, recipient: str, *, event: str, dedupe_key: str, **fields: Any
) -> Notification | None:
    """Get-or-create a notification row, deduped. Returns None if already sent."""
    existing = Notification.objects.filter(
        dedupe_key=dedupe_key, channel=channel, recipient=recipient
    ).first()
    if existing is not None:
        return None if existing.status == NotificationStatus.SENT else existing
    try:
        return Notification.objects.create(
            event=event, channel=channel, recipient=recipient, dedupe_key=dedupe_key, **fields
        )
    except IntegrityError:
        # Concurrent dispatch created it first — treat as already handled.
        return None


def dispatch(
    event: str,
    *,
    context: dict[str, Any],
    dedupe_key: str,
    email_to: str | list[str] | None = None,
    telegram_chat_id: str | list[str] | None = None,
    user: Any = None,
) -> list[str]:
    """Render + persist + enqueue a notification across the requested channels.

    ``user`` (when given) is recorded on each row so delivery can resolve that
    user's own settings (e.g. their Telegram bot token).
    """
    ctx = {**base_context(), **context}
    user_obj = user if (user is not None and getattr(user, "is_authenticated", False)) else None
    created: list[str] = []

    for to in _as_list(email_to):
        try:
            subject, html, text = events.render_email(event, ctx)
            note = _ensure(
                Channel.EMAIL,
                to,
                event=event,
                dedupe_key=dedupe_key,
                user=user_obj,
                subject=subject,
                body_html=html,
                body_text=text,
                context=_json_safe(ctx),
            )
            if note is not None:
                created.append(str(note.id))
                _enqueue_delivery(str(note.id))
        except Exception:  # noqa: BLE001 - never let notifications break the caller
            logger.exception("Failed to queue email notification %s to %s", event, to)

    for chat_id in _as_list(telegram_chat_id):
        try:
            text = events.render_telegram(event, ctx)
            note = _ensure(
                Channel.TELEGRAM,
                str(chat_id),
                event=event,
                dedupe_key=dedupe_key,
                user=user_obj,
                body_text=text,
                context=_json_safe(ctx),
            )
            if note is not None:
                created.append(str(note.id))
                _enqueue_delivery(str(note.id))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to queue telegram notification %s to %s", event, chat_id)

    return created


def _as_list(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    # De-duplicate while preserving order; drop falsy entries.
    seen: dict[str, None] = {}
    for v in value:
        if v:
            seen.setdefault(v, None)
    return list(seen)


def _json_safe(ctx: dict[str, Any]) -> dict[str, Any]:
    import json

    from rest_framework.utils.encoders import JSONEncoder

    return json.loads(json.dumps(ctx, cls=JSONEncoder))
