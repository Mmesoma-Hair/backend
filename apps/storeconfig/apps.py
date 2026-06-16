from __future__ import annotations

from django.apps import AppConfig


class StoreConfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.storeconfig"
    label = "storeconfig"
    verbose_name = "Store Configuration"
