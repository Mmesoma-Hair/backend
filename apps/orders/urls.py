from __future__ import annotations

from django.urls import path

from .views import (
    CheckoutView,
    OrderDetailView,
    OrderHistoryView,
    OrderStatusView,
    SharedCheckoutView,
)

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("checkout/shared/<str:token>/", SharedCheckoutView.as_view(), name="checkout-shared"),
    path("orders/", OrderHistoryView.as_view(), name="order-history"),
    path("orders/<str:number>/status/", OrderStatusView.as_view(), name="order-status"),
    path("orders/<str:number>/", OrderDetailView.as_view(), name="order-detail"),
]
