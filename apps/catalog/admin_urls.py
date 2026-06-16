from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import (
    BrandAdminViewSet,
    CategoryAdminViewSet,
    OptionTypeAdminViewSet,
    OptionValueAdminViewSet,
    ProductAdminViewSet,
    ProductImageAdminViewSet,
    VariantAdminViewSet,
)

router = DefaultRouter()
router.register("categories", CategoryAdminViewSet, basename="admin-category")
router.register("brands", BrandAdminViewSet, basename="admin-brand")
router.register("option-types", OptionTypeAdminViewSet, basename="admin-option-type")
router.register("option-values", OptionValueAdminViewSet, basename="admin-option-value")
router.register("variants", VariantAdminViewSet, basename="admin-variant")
router.register("images", ProductImageAdminViewSet, basename="admin-image")
router.register("products", ProductAdminViewSet, basename="admin-product")

urlpatterns = router.urls
