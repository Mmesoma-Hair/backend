"""Public (read-only) blog serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.images import image_urls

from .models import BlogCategory, BlogPost


class BlogCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogCategory
        fields = ("id", "name", "slug", "description")


def _cover(obj: BlogPost) -> dict[str, str] | None:
    return image_urls(obj.cover_image_public_id) if obj.cover_image_public_id else None


class BlogPostListSerializer(serializers.ModelSerializer):
    category = BlogCategorySerializer(read_only=True)
    cover = serializers.SerializerMethodField()
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = (
            "id",
            "title",
            "slug",
            "excerpt",
            "cover",
            "category",
            "tags",
            "published_at",
            "reading_minutes",
            "author_name",
        )

    def get_cover(self, obj: BlogPost) -> dict[str, str] | None:
        return _cover(obj)

    def get_author_name(self, obj: BlogPost) -> str:
        return (obj.author.full_name or obj.author.email.split("@")[0]) if obj.author else ""


class BlogPostDetailSerializer(BlogPostListSerializer):
    class Meta(BlogPostListSerializer.Meta):
        fields = BlogPostListSerializer.Meta.fields + (
            "body",
            "meta_title",
            "meta_description",
            "updated_at",
        )
