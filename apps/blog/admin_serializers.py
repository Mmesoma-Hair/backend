"""Admin (read/write) blog serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.images import image_urls

from .models import BlogCategory, BlogPost


class BlogCategoryAdminSerializer(serializers.ModelSerializer):
    post_count = serializers.SerializerMethodField()

    class Meta:
        model = BlogCategory
        fields = ("id", "name", "slug", "description", "post_count")
        extra_kwargs = {"slug": {"required": False}}

    def get_post_count(self, obj: BlogCategory) -> int:
        return obj.posts.count()


class BlogPostAdminSerializer(serializers.ModelSerializer):
    cover = serializers.SerializerMethodField()
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = (
            "id",
            "title",
            "slug",
            "excerpt",
            "body",
            "cover_image_public_id",
            "cover",
            "category",
            "tags",
            "status",
            "published_at",
            "meta_title",
            "meta_description",
            "reading_minutes",
            "author_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "cover",
            "reading_minutes",
            "published_at",
            "author_name",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "slug": {"required": False},
            "excerpt": {"required": False},
            "body": {"required": False},
            "meta_title": {"required": False},
            "meta_description": {"required": False},
        }

    def get_cover(self, obj: BlogPost) -> dict | None:
        return image_urls(obj.cover_image_public_id) if obj.cover_image_public_id else None

    def get_author_name(self, obj: BlogPost) -> str:
        return (obj.author.full_name or obj.author.email.split("@")[0]) if obj.author else ""


class AiGenerateSerializer(serializers.Serializer):
    """Input for the AI blog writer."""

    topic = serializers.CharField()
    tone = serializers.CharField(required=False, allow_blank=True, default="")
    keywords = serializers.CharField(required=False, allow_blank=True, default="")
