from __future__ import annotations

from django.urls import path

from .admin_views import PaymentConfigView, PaymentTestView

urlpatterns = [
    path("config/", PaymentConfigView.as_view(), name="admin-payment-config"),
    path("test/", PaymentTestView.as_view(), name="admin-payment-test"),
]
