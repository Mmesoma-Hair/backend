"""Payment business logic: intents, webhook processing, mock confirmation."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction

from apps.common.exceptions import ConflictError, DomainError
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus

from .models import Payment, WebhookEvent
from .providers import MockProvider, get_payment_provider


class WebhookSignatureError(DomainError):
    status_code = 400
    default_code = "invalid_signature"


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
    intent = provider.create_intent(
        amount=order.total_charged,
        currency=order.currency,
        metadata={"order_number": order.number},
    )
    return Payment.objects.create(
        order=order,
        provider=provider.name,
        status=Payment.Status.PENDING,
        amount=order.total_charged,
        currency=order.currency,
        intent_id=intent["intent_id"],
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


def process_webhook(*, provider_name: str, payload: bytes, signature: str) -> dict[str, Any]:
    """Verify, dedupe, and apply a provider webhook event (idempotent)."""
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

    if event.get("status") == "succeeded":
        payment = Payment.objects.filter(intent_id=event.get("intent_id")).first()
        if payment is not None:
            _apply_succeeded(payment)
            return {"status": "applied", "order": payment.order.number}
    return {"status": "ignored", "event_id": event_id}


def confirm_mock_payment(payment: Payment) -> dict[str, Any]:
    """Simulate the provider sending a success webhook (mock provider only)."""
    provider = get_payment_provider()
    if not isinstance(provider, MockProvider):
        raise ConflictError("Manual confirmation is only available with the mock provider.")
    body, signature = provider.build_event(intent_id=payment.intent_id, status="succeeded")
    return process_webhook(provider_name=provider.name, payload=body, signature=signature)
