"""Reusable base models and mixins shared by every domain app.

These provide consistent primary keys, timestamps, soft-delete semantics, and a
generic audit log. Domain models inherit the mixins they need rather than
re-declaring the same fields.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Adds self-managing ``created_at`` / ``updated_at`` timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """Uses a non-sequential UUID primary key (safe to expose in URLs)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self) -> SoftDeleteQuerySet:
        return self.filter(deleted_at__isnull=True)

    def dead(self) -> SoftDeleteQuerySet:
        return self.filter(deleted_at__isnull=False)

    def delete(self) -> tuple[int, dict[str, int]]:  # type: ignore[override]
        count = self.update(deleted_at=timezone.now())
        return count, {}

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        return super().delete()


class SoftDeleteManager(models.Manager):
    """Default manager that hides soft-deleted rows."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class AllObjectsManager(models.Manager):
    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(models.Model):
    """Marks rows deleted instead of removing them.

    ``objects`` returns only live rows; ``all_objects`` returns everything.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, default=None, db_index=True)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:  # type: ignore[override]
        self.deleted_at = timezone.now()
        self.save(
            update_fields=(
                ["deleted_at", "updated_at"] if hasattr(self, "updated_at") else ["deleted_at"]
            )
        )
        return 1, {}

    def hard_delete(
        self, using: Any = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])


class BaseModel(UUIDModel, TimeStampedModel):
    """Common base: UUID pk + timestamps. The default for domain models."""

    class Meta:
        abstract = True


class AuditLog(TimeStampedModel):
    """Immutable record of an admin/config-mutating action.

    Written by the service layer (and helpers in :mod:`apps.common.audit`) for
    any change to config, orders, or rates, capturing actor, action, target,
    and a before/after diff.
    """

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        OTHER = "other", "Other"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    actor_label = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human-readable actor snapshot (e.g. email) preserved even if the user is deleted.",
    )
    action = models.CharField(max_length=16, choices=Action.choices, default=Action.OTHER)
    target_type = models.CharField(
        max_length=120, help_text="Logical resource type, e.g. 'storeconfig.Setting'."
    )
    target_id = models.CharField(max_length=120, blank=True)
    changes = models.JSONField(
        default=dict, blank=True, help_text="{'field': {'before': x, 'after': y}}"
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.action} {self.target_type}#{self.target_id} by {self.actor_label or 'system'}"
        )
