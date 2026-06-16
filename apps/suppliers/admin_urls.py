from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import SupplierAdminViewSet

router = DefaultRouter()
router.register("suppliers", SupplierAdminViewSet, basename="admin-supplier")

urlpatterns = router.urls
