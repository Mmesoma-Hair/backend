"""Read-side queries for the public blog."""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from .models import BlogPost, BlogStatus


def published_posts() -> QuerySet[BlogPost]:
    return BlogPost.objects.filter(
        status=BlogStatus.PUBLISHED, published_at__lte=timezone.now()
    ).select_related("category", "author")


def post_by_slug(slug: str) -> BlogPost | None:
    return published_posts().filter(slug=slug).first()


def related_posts(post: BlogPost, limit: int = 3) -> QuerySet[BlogPost]:
    qs = published_posts().exclude(pk=post.pk)
    if post.category_id:
        same = qs.filter(category_id=post.category_id)
        if same.exists():
            return same[:limit]
    return qs[:limit]


def search_posts(qs: QuerySet[BlogPost], term: str) -> QuerySet[BlogPost]:
    return qs.filter(
        Q(title__icontains=term) | Q(excerpt__icontains=term) | Q(body__icontains=term)
    )
