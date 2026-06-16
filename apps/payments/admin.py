from __future__ import annotations

from django.contrib import admin

from .models import Payment, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "intent_id",
        "order",
        "provider",
        "status",
        "amount",
        "currency",
        "paid_by_user",
    )
    list_filter = ("provider", "status")
    search_fields = ("intent_id", "order__number", "payer_email")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_id", "event_type", "created_at")
    search_fields = ("event_id",)
