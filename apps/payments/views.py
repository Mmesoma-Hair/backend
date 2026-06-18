"""Payment webhook + mock confirmation endpoints."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import DomainError

from . import services
from .models import Payment
from .providers import get_payment_provider


class PaymentWebhookView(APIView):
    """Receives provider webhooks. Verifies signature; idempotent on event id."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(request=None, responses={200: dict}, tags=["payments"])
    def post(self, request: Request) -> Response:
        provider = get_payment_provider()
        signature = request.headers.get(provider.signature_header, "")
        result = services.process_webhook(
            provider_name=provider.name,
            payload=request.body,
            signature=signature,
        )
        return Response(result)


class MockConfirmView(APIView):
    """Dev/test helper: simulate the provider confirming a payment.

    Lets the mock "Pay now" button drive an order to paid without a real gateway.
    With a real provider this returns 409 (use the gateway + webhook instead).
    """

    permission_classes = [AllowAny]

    @extend_schema(request=dict, responses={200: dict}, tags=["payments"])
    def post(self, request: Request) -> Response:
        order_number = request.data.get("order_number")
        if not order_number:
            raise DomainError("order_number is required.", code="order_required")
        payment = Payment.objects.filter(order__number=order_number).order_by("-created_at").first()
        if payment is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        result = services.confirm_mock_payment(payment)
        return Response(result)
