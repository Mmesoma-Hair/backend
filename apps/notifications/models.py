"""Notification delivery log.

Every notification (one row per channel + recipient) is persisted so delivery is
observable, retryable, and idempotent: a ``dedupe_key`` prevents the same logical
event from being sent twice to the same recipient on the same channel.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class Channel(models.TextChoices):
    EMAIL = "email", "Email"
    TELEGRAM = "telegram", "Telegram"


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class Notification(BaseModel):
    event = models.CharField(max_length=60, db_index=True)
    channel = models.CharField(max_length=12, choices=Channel.choices)
    recipient = models.CharField(max_length=255)
    # The user this targets (if any) — lets delivery resolve per-user settings
    # (e.g. their own Telegram bot token) without storing secrets on the row.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    subject = models.CharField(max_length=255, blank=True)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)

    status = models.CharField(
        max_length=12,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    provider_response = models.JSONField(default=dict, blank=True)

    # Idempotency: dedupes identical sends (event+target). Unique per channel+recipient.
    dedupe_key = models.CharField(max_length=200, db_index=True)
    context = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key", "channel", "recipient"], name="uniq_notification_dedupe"
            ),
        ]
        indexes = [models.Index(fields=["status", "channel"])]

    def __str__(self) -> str:
        return f"{self.event} → {self.channel}:{self.recipient} ({self.status})"
