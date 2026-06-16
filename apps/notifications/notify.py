"""High-level notification helpers.

These build the right context + recipients for each business event and call
:func:`apps.notifications.services.dispatch`. Every helper is wrapped so a
notification problem can never break the action that triggered it.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from . import events
from .services import base_context, dispatch

logger = logging.getLogger(__name__)


def _ops_chat() -> str | None:
    chat = getattr(settings, "TELEGRAM_DEFAULT_CHAT_ID", "")
    disabled = getattr(settings, "NOTIFICATIONS_TELEGRAM_BACKEND", "console") == "disabled"
    return chat or None if not disabled else None


def _profile(user: Any) -> Any:
    return getattr(user, "profile", None) if user else None


def _email_enabled(user: Any) -> bool:
    """Whether to email a user. Guests (no profile) always get transactional mail."""
    profile = _profile(user)
    return True if profile is None else bool(profile.notify_email)


def _user_telegram(user: Any) -> str | None:
    """The user's Telegram chat id, only if they've opted in and connected a bot."""
    profile = _profile(user)
    if profile is None or not profile.notify_telegram:
        return None
    return profile.telegram_chat_id if profile.telegram_connected else None


def _order_context(order: Any) -> dict[str, Any]:
    frontend = base_context()["frontend_url"]
    lines = list(order.lines.all())
    return {
        "order_number": order.number,
        "order_total": f"{order.currency} {order.total_charged}",
        "order_status": order.status,
        "items": [
            {
                "title": ln.title,
                "quantity": ln.quantity,
                "line_total": f"{order.currency} {ln.line_total_charged}",
            }
            for ln in lines
        ],
        "items_count": sum(ln.quantity for ln in lines),
        "contact_email": order.contact_email,
        "paid_by": order.payer_email or (order.paid_by_user.email if order.paid_by_user_id else ""),
        "order_url": f"{frontend}/orders/{order.number}",
    }


def send_welcome(user: Any) -> None:
    try:
        dispatch(
            events.WELCOME,
            context={"name": user.full_name or user.email},
            dedupe_key=f"welcome:{user.id}",
            email_to=user.email,
            user=user,
        )
    except Exception:  # noqa: BLE001
        logger.exception("send_welcome failed for %s", getattr(user, "id", "?"))


def send_email_verification(user: Any, *, token: str) -> None:
    """Send the email-verification link (account-level; always to the user)."""
    try:
        verify_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/verify-email?token={token}"
        dispatch(
            events.EMAIL_VERIFICATION,
            context={"name": user.full_name or user.email, "verify_url": verify_url},
            dedupe_key=f"email_verification:{user.id}:{token[:12]}",
            email_to=user.email,
            user=user,
        )
    except Exception:  # noqa: BLE001
        logger.exception("send_email_verification failed for %s", getattr(user, "id", "?"))


def send_password_reset(*, email: str, uid: str, token: str) -> None:
    try:
        reset_url = (
            f"{settings.FRONTEND_BASE_URL.rstrip('/')}/reset-password?uid={uid}&token={token}"
        )
        dispatch(
            events.PASSWORD_RESET,
            context={"reset_url": reset_url},
            dedupe_key=f"password_reset:{uid}:{token[:10]}",
            email_to=email,
        )
    except Exception:  # noqa: BLE001
        logger.exception("send_password_reset failed for %s", email)


def _order_email_recipients(order: Any) -> list[str]:
    """Owner (if they allow email) + payer (guest/other, always for their receipt)."""
    recipients: list[str] = []
    if order.contact_email and _email_enabled(order.owner):
        recipients.append(order.contact_email)
    if order.payer_email and order.payer_email != order.contact_email:
        recipients.append(order.payer_email)
    return recipients


def on_order_paid(order: Any) -> None:
    """Notify the owner + payer (per their channel prefs) and alert store ops."""
    try:
        ctx = _order_context(order)
        dispatch(
            events.ORDER_CONFIRMATION,
            context=ctx,
            dedupe_key=f"order_confirmation:{order.id}",
            email_to=_order_email_recipients(order),
            telegram_chat_id=_user_telegram(order.owner),
            user=order.owner,
        )
        ops = _ops_chat()
        if ops:
            dispatch(
                events.OPS_NEW_ORDER,
                context=ctx,
                dedupe_key=f"ops_new_order:{order.id}",
                telegram_chat_id=ops,
            )
    except Exception:  # noqa: BLE001
        logger.exception("on_order_paid notifications failed for %s", getattr(order, "number", "?"))


def on_shipment_shipped(order: Any, shipment: Any) -> None:
    try:
        ctx = {
            **_order_context(order),
            "carrier": shipment.carrier,
            "tracking_number": shipment.tracking_number,
            "shipment_kind": shipment.kind,
        }
        email_to = (
            order.contact_email if (order.contact_email and _email_enabled(order.owner)) else None
        )
        dispatch(
            events.SHIPMENT_UPDATE,
            context=ctx,
            dedupe_key=f"shipment_update:{shipment.id}",
            email_to=email_to,
            telegram_chat_id=_user_telegram(order.owner),
            user=order.owner,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "on_shipment_shipped notifications failed for %s", getattr(shipment, "id", "?")
        )
