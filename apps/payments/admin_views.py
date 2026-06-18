"""Admin payments configuration: provider + keys, webhook URL, test connection.

Secrets are write-only — the API returns only whether each is set, never the
value. Provider keys live in storeconfig (DB), audit-logged on change.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole
from apps.storeconfig import selectors as config_selectors
from apps.storeconfig import services as config_services

from . import config
from .models import WebhookEvent
from .providers import get_payment_provider

# storeconfig keys this page manages. (secret? used for masking)
_KEYS = {
    "provider": ("payments.provider", False),
    "paystack_public_key": ("payments.paystack_public_key", False),
    "paystack_secret_key": ("payments.paystack_secret_key", True),
    "flutterwave_public_key": ("payments.flutterwave_public_key", False),
    "flutterwave_secret_key": ("payments.flutterwave_secret_key", True),
    "flutterwave_secret_hash": ("payments.flutterwave_secret_hash", True),
}


def _is_set(storeconfig_key: str, env_value: str) -> bool:
    stored = config_selectors.get_all_settings().get(storeconfig_key)
    return bool(stored or env_value)


class PaymentConfigWriteSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["mock", "paystack", "flutterwave"], required=False)
    paystack_public_key = serializers.CharField(required=False, allow_blank=True)
    paystack_secret_key = serializers.CharField(required=False, allow_blank=True)
    flutterwave_public_key = serializers.CharField(required=False, allow_blank=True)
    flutterwave_secret_key = serializers.CharField(required=False, allow_blank=True)
    flutterwave_secret_hash = serializers.CharField(required=False, allow_blank=True)


def _config_payload() -> dict:
    last = (
        WebhookEvent.objects.filter(provider=config.provider_name()).order_by("-created_at").first()
    )
    return {
        "provider": config.provider_name(),
        "webhook_url": config.webhook_url(),
        # Public keys are returned in full; secrets only as "is set".
        "paystack_public_key": config.paystack_public_key(),
        "paystack_secret_set": _is_set(
            "payments.paystack_secret_key", config.paystack_secret_key()
        ),
        "flutterwave_public_key": config.flutterwave_public_key(),
        "flutterwave_secret_set": _is_set(
            "payments.flutterwave_secret_key", config.flutterwave_secret_key()
        ),
        "flutterwave_hash_set": _is_set(
            "payments.flutterwave_secret_hash", config.flutterwave_secret_hash()
        ),
        "last_webhook_at": last.created_at.isoformat() if last else None,
        "last_webhook_event": last.event_type if last else "",
    }


class PaymentConfigView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: dict}, tags=["payments-admin"])
    def get(self, request: Request) -> Response:
        return Response(_config_payload())

    @extend_schema(
        request=PaymentConfigWriteSerializer, responses={200: dict}, tags=["payments-admin"]
    )
    def patch(self, request: Request) -> Response:
        serializer = PaymentConfigWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        for field, (key, secret) in _KEYS.items():
            if field not in data:
                continue
            value = data[field]
            # Blank secret = keep the existing one (don't overwrite with empty).
            if secret and value == "":
                continue
            config_services.set_setting(key, value, actor=request.user)
        return Response(_config_payload())


class PaymentTestView(APIView):
    """Validate the active provider's keys via a live authenticated API call."""

    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: dict}, tags=["payments-admin"])
    def post(self, request: Request) -> Response:
        result = get_payment_provider().verify_credentials()
        return Response(result)
