from __future__ import annotations

from django.contrib import admin

from .models import Supplier, SupplierStock


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "adapter", "is_active", "sync_cadence_minutes")
    list_filter = ("is_active", "adapter")
    search_fields = ("name", "code")


@admin.register(SupplierStock)
class SupplierStockAdmin(admin.ModelAdmin):
    list_display = ("supplier", "sku", "available")
    search_fields = ("sku",)
    list_filter = ("supplier",)
