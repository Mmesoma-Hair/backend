from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import AuditLogViewSet

router = DefaultRouter()
router.register("audit", AuditLogViewSet, basename="admin-audit")

urlpatterns = router.urls
