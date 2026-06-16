from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import CouponAdminViewSet

router = DefaultRouter()
router.register("coupons", CouponAdminViewSet, basename="admin-coupon")

urlpatterns = router.urls
