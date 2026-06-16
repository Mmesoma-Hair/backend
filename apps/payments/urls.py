from __future__ import annotations

from django.urls import path

from .views import MockConfirmView, PaymentWebhookView

urlpatterns = [
    path("webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
    path("confirm/", MockConfirmView.as_view(), name="payment-confirm"),
]
