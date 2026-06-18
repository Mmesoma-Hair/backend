from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import OrderAdminViewSet, OrderInquiryAdminViewSet

router = DefaultRouter()
router.register("orders", OrderAdminViewSet, basename="admin-order")
router.register("order-inquiries", OrderInquiryAdminViewSet, basename="admin-order-inquiry")

urlpatterns = router.urls
