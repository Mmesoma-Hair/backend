from __future__ import annotations

from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "target_type", "target_id", "actor_label")
    list_filter = ("action", "target_type")
    search_fields = ("target_id", "actor_label")
    readonly_fields = (
        "actor",
        "actor_label",
        "action",
        "target_type",
        "target_id",
        "changes",
        "metadata",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object | None = None) -> bool:
        return False
