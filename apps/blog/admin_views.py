"""Admin blog management (role: admin) + AI writer."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.common.audit_mixins import AuditedModelViewSet

from . import ai, services
from .admin_serializers import (
    AiGenerateSerializer,
    BlogCategoryAdminSerializer,
    BlogPostAdminSerializer,
)
from .models import BlogCategory, BlogPost, BlogStatus


class BlogCategoryAdminViewSet(AuditedModelViewSet):
    permission_classes = [IsAdminRole]
    queryset = BlogCategory.objects.all()
    serializer_class = BlogCategoryAdminSerializer


class BlogPostAdminViewSet(AuditedModelViewSet):
    permission_classes = [IsAdminRole]
    queryset = BlogPost.objects.select_related("category", "author").all()
    serializer_class = BlogPostAdminSerializer
    filterset_fields = ["status", "category"]
    search_fields = ["title", "slug", "excerpt"]

    def perform_create(self, serializer: BlogPostAdminSerializer) -> None:
        post = serializer.save(author=self.request.user)
        services.prepare_post(post)
        post.save()

    def perform_update(self, serializer: BlogPostAdminSerializer) -> None:
        post = serializer.save()
        services.prepare_post(post)
        post.save()

    @extend_schema(responses={200: BlogPostAdminSerializer}, tags=["blog-admin"])
    @action(detail=True, methods=["post"])
    def publish(self, request: Request, pk: str | None = None) -> Response:
        post = self.get_object()
        post.status = BlogStatus.PUBLISHED
        services.prepare_post(post)
        post.save()
        return Response(BlogPostAdminSerializer(post).data)

    @extend_schema(responses={200: BlogPostAdminSerializer}, tags=["blog-admin"])
    @action(detail=True, methods=["post"])
    def unpublish(self, request: Request, pk: str | None = None) -> Response:
        post = self.get_object()
        post.status = BlogStatus.DRAFT
        services.prepare_post(post)
        post.save()
        return Response(BlogPostAdminSerializer(post).data)

    @extend_schema(request=AiGenerateSerializer, responses={200: dict}, tags=["blog-admin"])
    @action(detail=False, methods=["post"])
    def ai(self, request: Request) -> Response:
        """Generate a draft blog post with the configured AI model (OpenRouter)."""
        serializer = AiGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        result = ai.generate_blog(
            topic=d["topic"], tone=d.get("tone", ""), keywords=d.get("keywords", "")
        )
        return Response(result)
