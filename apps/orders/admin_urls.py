from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import OrderAdminViewSet

router = DefaultRouter()
router.register("orders", OrderAdminViewSet, basename="admin-order")

urlpatterns = router.urls
