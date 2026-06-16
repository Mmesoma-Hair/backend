from __future__ import annotations

from django.urls import path

from .views import (
    CartCouponDetailView,
    CartCouponsView,
    CartItemDetailView,
    CartItemsView,
    CartShareView,
    CartShippingView,
    CartView,
    SharedCartView,
)

urlpatterns = [
    path("", CartView.as_view(), name="cart"),
    path("items/", CartItemsView.as_view(), name="cart-items"),
    path("items/<uuid:line_id>/", CartItemDetailView.as_view(), name="cart-item-detail"),
    path("coupons/", CartCouponsView.as_view(), name="cart-coupons"),
    path("coupons/<str:code>/", CartCouponDetailView.as_view(), name="cart-coupon-detail"),
    path("shipping/", CartShippingView.as_view(), name="cart-shipping"),
    path("share/", CartShareView.as_view(), name="cart-share"),
    path("shared/<str:token>/", SharedCartView.as_view(), name="cart-shared"),
]
