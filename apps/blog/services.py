"""Blog business logic: slug, reading time, excerpt, publish state."""

from __future__ import annotations

import re

from django.utils import timezone
from django.utils.text import slugify

from .models import BlogPost, BlogStatus, unique_slug

_WORDS_PER_MINUTE = 200


def _strip_markdown(md: str) -> str:
    text = re.sub(r"`{1,3}[^`]*`{1,3}", " ", md)  # code
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)  # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> text
    text = re.sub(r"[#>*_~\-`]+", " ", text)  # markdown punctuation
    return re.sub(r"\s+", " ", text).strip()


def compute_reading_minutes(body: str) -> int:
    words = len(_strip_markdown(body).split())
    return max(1, round(words / _WORDS_PER_MINUTE))


def compute_excerpt(body: str, limit: int = 180) -> str:
    text = _strip_markdown(body)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "…"


def prepare_post(post: BlogPost) -> BlogPost:
    """Fill derived fields before saving (slug, reading time, excerpt, publish ts)."""
    if not post.slug:
        post.slug = unique_slug(BlogPost, slugify(post.title) or "post", exclude_pk=post.pk)
    post.reading_minutes = compute_reading_minutes(post.body)
    if not post.excerpt.strip():
        post.excerpt = compute_excerpt(post.body)
    if not post.meta_description.strip():
        post.meta_description = post.excerpt[:300]

    if post.status == BlogStatus.PUBLISHED and post.published_at is None:
        post.published_at = timezone.now()
    if post.status == BlogStatus.DRAFT:
        post.published_at = None
    return post
