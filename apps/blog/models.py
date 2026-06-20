"""Blog domain models.

Posts are authored in **Markdown** (``body``) — clean for the AI writer and
renders to semantic HTML on the storefront (good for SEO). Each post carries its
own SEO fields (meta title/description, slug, cover image) and a publish state.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.common.models import BaseModel


def unique_slug(model: type[models.Model], base: str, *, exclude_pk: object = None) -> str:
    """A slug unique within ``model`` (appends -2, -3, … on collision)."""
    base = base or "post"
    slug, i = base, 2
    qs = model.objects.all()
    while qs.filter(slug=slug).exclude(pk=exclude_pk).exists():
        slug, i = f"{base}-{i}", i + 1
    return slug


class BlogCategory(BaseModel):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "blog categories"

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.slug:
            self.slug = unique_slug(
                BlogCategory, slugify(self.name) or "category", exclude_pk=self.pk
            )
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class BlogStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"


class BlogPost(BaseModel):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    excerpt = models.TextField(blank=True)
    body = models.TextField(blank=True, help_text="Markdown content.")
    cover_image_public_id = models.CharField(max_length=255, blank=True)
    category = models.ForeignKey(
        BlogCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posts",
    )
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20, choices=BlogStatus.choices, default=BlogStatus.DRAFT, db_index=True
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blog_posts",
    )
    # SEO
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.CharField(max_length=320, blank=True)
    reading_minutes = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("-published_at", "-created_at")
        indexes = [models.Index(fields=["status", "published_at"])]

    def __str__(self) -> str:
        return self.title

    @property
    def is_published(self) -> bool:
        return self.status == BlogStatus.PUBLISHED
