"""Payment business logic: intents, webhook processing, mock confirmation."""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.common.exceptions import ConflictError, DomainError
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus

from .models import Payment, WebhookEvent
from .providers import MockProvider, PaymentError, get_payment_provider


class WebhookSignatureError(DomainError):
    status_code = 400
    default_code = "invalid_signature"


class PaymentVerificationError(DomainError):
    # 5xx so the gateway retries the webhook if our re-verification call failed.
    status_code = 503
    default_code = "verification_unavailable"


@transaction.atomic
def create_payment_for_order(
    order: Order,
    *,
    idempotency_key: str,
    payer_user: Any = None,
    payer_email: str = "",
    payer_name: str = "",
) -> Payment:
    existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing

    provider = get_payment_provider()
    # A unique gateway reference we can match the webhook back to this payment.
    reference = f"{order.number}-{secrets.token_hex(6)}"
    return_url = settings.PAYMENT_RETURN_URL.format(order=order.number)
    intent = provider.create_intent(
        amount=order.total_charged,
        currency=order.currency,
        reference=reference,
        email=payer_email or order.contact_email,
        redirect_url=return_url,
        metadata={"order_number": order.number, "reference": reference},
    )
    return Payment.objects.create(
        order=order,
        provider=provider.name,
        status=Payment.Status.PENDING,
        amount=order.total_charged,
        currency=order.currency,
        intent_id=intent["intent_id"],
        authorization_url=intent.get("authorization_url", ""),
        paid_by_user=(
            payer_user if (payer_user and getattr(payer_user, "is_authenticated", False)) else None
        ),
        payer_email=payer_email,
        payer_name=payer_name,
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def _apply_succeeded(payment: Payment) -> None:
    if payment.status == Payment.Status.SUCCEEDED:
        return
    payment.status = Payment.Status.SUCCEEDED
    payment.save(update_fields=["status", "updated_at"])
    order = payment.order
    if order.status == OrderStatus.PENDING:
        order_services.mark_paid(
            order,
            paid_by_user=payment.paid_by_user,
            payer_email=payment.payer_email,
            payer_name=payment.payer_name,
        )


def _apply_failed(payment: Payment) -> None:
    if payment.status not in (Payment.Status.SUCCEEDED, Payment.Status.REFUNDED):
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status", "updated_at"])


def _confirm_with_gateway(provider: Any, payment: Payment, event: dict[str, Any]) -> bool:
    """Re-verify the transaction with the gateway API (real providers only).

    Never trust the webhook body alone — the gateway's own verify endpoint is the
    source of truth. Confirms status, that the reference belongs to this payment,
    that the amount paid covers what we charged, and that the currency matches.
    Mock provider has no API → already signature-verified, trusted directly.
    """
    try:
        verified = provider.verify_transaction(
            reference=payment.intent_id, txn_id=str(event.get("event_id", ""))
        )
    except PaymentError as exc:
        raise PaymentVerificationError(str(exc)) from exc
    if verified is None:
        return True  # mock / unsupported
    if verified.get("status") != "succeeded":
        return False
    # The verified transaction must be the one we created for this payment.
    ref = verified.get("reference") or ""
    if ref and ref != payment.intent_id:
        return False
    # Amount paid must cover what we charged (guards under-payment / tampering).
    amount = Decimal(str(verified.get("amount") or 0))
    if amount + Decimal("0.01") < payment.amount:
        return False
    if verified.get("currency") and verified["currency"] != payment.currency.upper():
        return False
    return True


def process_webhook(*, provider_name: str, payload: bytes, signature: str) -> dict[str, Any]:
    """Verify, dedupe, re-confirm, and apply a provider webhook event (idempotent)."""
    provider = get_payment_provider()
    if not provider.verify_signature(payload=payload, signature=signature):
        raise WebhookSignatureError("Invalid webhook signature.")

    event = provider.parse_event(payload)
    event_id = event.get("event_id")
    if not event_id:
        raise DomainError("Webhook missing event id.", code="invalid_event")

    # Idempotency: a given provider event is processed at most once.
    try:
        with transaction.atomic():
            WebhookEvent.objects.create(
                provider=provider_name,
                event_id=event_id,
                event_type=event.get("type", ""),
                payload=event,
            )
    except IntegrityError:
        return {"status": "duplicate", "event_id": event_id}

    payment = Payment.objects.filter(intent_id=event.get("intent_id")).first()
    if payment is None:
        return {"status": "ignored", "event_id": event_id}

    if event.get("status") == "succeeded":
        if _confirm_with_gateway(provider, payment, event):
            _apply_succeeded(payment)
            return {"status": "applied", "order": payment.order.number}
        return {"status": "unverified", "event_id": event_id}

    if event.get("status") in ("failed", "abandoned"):
        _apply_failed(payment)
        return {"status": "failed_recorded", "order": payment.order.number}

    return {"status": "ignored", "event_id": event_id}


def confirm_mock_payment(payment: Payment) -> dict[str, Any]:
    """Simulate the provider sending a success webhook (mock provider only)."""
    provider = get_payment_provider()
    if not isinstance(provider, MockProvider):
        raise ConflictError("Manual confirmation is only available with the mock provider.")
    body, signature = provider.build_event(intent_id=payment.intent_id, status="succeeded")
    return process_webhook(provider_name=provider.name, payload=body, signature=signature)
