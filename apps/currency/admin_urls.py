from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import CurrencyAdminViewSet

router = DefaultRouter()
router.register("currencies", CurrencyAdminViewSet, basename="admin-currency")

urlpatterns = router.urls
