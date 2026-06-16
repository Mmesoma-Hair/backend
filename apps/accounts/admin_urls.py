from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import RoleChoicesView, UserAdminViewSet

router = DefaultRouter()
router.register("users", UserAdminViewSet, basename="admin-user")
router.register("roles", RoleChoicesView, basename="admin-role")

urlpatterns = router.urls
