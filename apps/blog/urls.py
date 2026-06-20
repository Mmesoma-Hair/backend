from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .views import BlogCategoryViewSet, BlogPostViewSet

router = DefaultRouter()
router.register("posts", BlogPostViewSet, basename="blog-post")
router.register("categories", BlogCategoryViewSet, basename="blog-category")

urlpatterns = router.urls
