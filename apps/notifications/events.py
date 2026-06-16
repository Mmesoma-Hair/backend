"""Notification event registry + template rendering.

Each event maps to a subject template and (by convention) email/telegram body
templates under ``notifications/{email,telegram}/<event>.{html,txt}``. Rendering
is defensive: a missing template degrades to a sensible default rather than
raising, so a notification never breaks the action that triggered it.
"""

from __future__ import annotations

import logging
from typing import Any

from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

WELCOME = "welcome"
EMAIL_VERIFICATION = "email_verification"
PASSWORD_RESET = "password_reset"
ORDER_CONFIRMATION = "order_confirmation"
PAYMENT_RECEIVED = "payment_received"
SHIPMENT_UPDATE = "shipment_update"
OPS_NEW_ORDER = "ops_new_order"

EVENTS: dict[str, dict[str, str]] = {
    WELCOME: {"subject": "Welcome to {store_name}"},
    EMAIL_VERIFICATION: {"subject": "Verify your {store_name} email"},
    PASSWORD_RESET: {"subject": "Reset your {store_name} password"},
    ORDER_CONFIRMATION: {"subject": "{store_name}: order {order_number} confirmed"},
    PAYMENT_RECEIVED: {"subject": "{store_name}: payment received for {order_number}"},
    SHIPMENT_UPDATE: {"subject": "{store_name}: order {order_number} has shipped"},
    OPS_NEW_ORDER: {"subject": "New paid order {order_number}"},
}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def subject_for(event: str, context: dict[str, Any]) -> str:
    template = EVENTS.get(event, {}).get("subject", "{store_name} notification")
    return template.format_map(_SafeDict(context))


def render_email(event: str, context: dict[str, Any]) -> tuple[str, str, str]:
    subject = subject_for(event, context)
    html = _safe_render(f"notifications/email/{event}.html", context)
    text = _safe_render(f"notifications/email/{event}.txt", context)
    if not text:
        text = subject
    return subject, html, text


def render_telegram(event: str, context: dict[str, Any]) -> str:
    text = _safe_render(f"notifications/telegram/{event}.txt", context)
    if text:
        return text
    # Fall back to the email text body, then the subject.
    return _safe_render(f"notifications/email/{event}.txt", context) or subject_for(event, context)


def _safe_render(template_name: str, context: dict[str, Any]) -> str:
    """Render a template, degrading to empty on any error.

    A missing template (or an engine quirk) must never break a notification —
    the caller falls back to the text body / subject, so an email/Telegram is
    still delivered.
    """
    try:
        return render_to_string(template_name, context).strip()
    except TemplateDoesNotExist:
        return ""
    except Exception:  # noqa: BLE001 - notifications must not depend on rendering
        logger.exception("Failed to render notification template %s", template_name)
        return ""
