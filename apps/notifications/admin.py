from __future__ import annotations

from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event", "channel", "recipient", "status", "attempts")
    list_filter = ("channel", "status", "event")
    search_fields = ("recipient", "event", "dedupe_key", "subject")
    readonly_fields = tuple(f.name for f in Notification._meta.fields)

    def has_add_permission(self, request: object) -> bool:
        return False
