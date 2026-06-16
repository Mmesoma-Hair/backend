from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .admin_views import StockAdminView, WarehouseAdminViewSet

router = DefaultRouter()
router.register("warehouses", WarehouseAdminViewSet, basename="admin-warehouse")

urlpatterns = [
    path("stock/", StockAdminView.as_view(), name="admin-stock"),
    *router.urls,
]
