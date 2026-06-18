"""Resolve payment gateway config: admin (storeconfig DB) overrides env.

Admins manage providers + keys from the dashboard; values fall back to env
settings when not set in the admin, so existing deployments keep working.
"""

from __future__ import annotations

from django.conf import settings

from apps.storeconfig.models import Setting


def _stored(key: str) -> str:
    """The admin-set value for ``key`` (a stored override row), or '' if unset.

    We read the row directly — not get_all_settings(), which merges in spec
    defaults and so can't tell "admin set it" from "using the default".
    """
    row = Setting.objects.filter(key=key).first()
    return str(row.value) if row and row.value not in (None, "") else ""


def provider_name() -> str:
    return _stored("payments.provider") or getattr(settings, "PAYMENT_PROVIDER", "mock")


def paystack_secret_key() -> str:
    return _stored("payments.paystack_secret_key") or settings.PAYSTACK_SECRET_KEY


def paystack_public_key() -> str:
    return _stored("payments.paystack_public_key") or settings.PAYSTACK_PUBLIC_KEY


def flutterwave_secret_key() -> str:
    return _stored("payments.flutterwave_secret_key") or settings.FLUTTERWAVE_SECRET_KEY


def flutterwave_public_key() -> str:
    return _stored("payments.flutterwave_public_key") or settings.FLUTTERWAVE_PUBLIC_KEY


def flutterwave_secret_hash() -> str:
    return _stored("payments.flutterwave_secret_hash") or settings.FLUTTERWAVE_SECRET_HASH


def webhook_url() -> str:
    base = settings.API_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/api/v1/payments/webhook/"
