from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import BlogCategoryAdminViewSet, BlogPostAdminViewSet

router = DefaultRouter()
router.register("posts", BlogPostAdminViewSet, basename="admin-blog-post")
router.register("categories", BlogCategoryAdminViewSet, basename="admin-blog-category")

urlpatterns = router.urls
