"""Payments: a payment against an order, plus webhook dedupe records.

A payment records the **payer** identity (which may differ from the order owner
for Pay-for-a-Friend) without changing order ownership. ``WebhookEvent`` gives
idempotent webhook processing — the same provider event is never applied twice.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.orders.models import Order


class Payment(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=40)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    intent_id = models.CharField(max_length=128, blank=True, db_index=True)
    # Hosted-checkout URL the shopper is redirected to (Paystack/Flutterwave).
    authorization_url = models.URLField(max_length=1000, blank=True)

    # Payer identity (may differ from order.owner).
    paid_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payments_made",
    )
    payer_email = models.EmailField(blank=True)
    payer_name = models.CharField(max_length=255, blank=True)

    idempotency_key = models.CharField(
        max_length=128, unique=True, null=True, blank=True, default=None
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.provider}:{self.intent_id or self.id} ({self.status})"


class WebhookEvent(BaseModel):
    """Records processed provider events so webhooks are idempotent."""

    provider = models.CharField(max_length=40)
    event_id = models.CharField(max_length=128)
    event_type = models.CharField(max_length=80, blank=True)
    payload = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_webhook_event"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_id}"
