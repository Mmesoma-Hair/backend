"""Account-related transactional emails.

Delegates to the ``notifications`` dispatch layer (async via Celery, with the
configured provider), so the email pipeline is consistent across the app.
"""

from __future__ import annotations

from apps.notifications.notify import send_password_reset


def send_password_reset_email(*, email: str, uid: str, token: str) -> None:
    send_password_reset(email=email, uid=uid, token=token)
