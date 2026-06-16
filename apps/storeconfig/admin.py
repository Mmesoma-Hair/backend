from __future__ import annotations

from django.contrib import admin

from .models import Setting


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ("key", "section", "value", "updated_at")
    list_filter = ("section",)
    search_fields = ("key",)
    readonly_fields = ("created_at", "updated_at")
