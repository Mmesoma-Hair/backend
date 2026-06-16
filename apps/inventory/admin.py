from __future__ import annotations

from django.contrib import admin

from .models import Reservation, StockItem, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_default", "is_active")
    list_filter = ("is_default", "is_active")
    search_fields = ("name", "code")


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ("variant", "warehouse", "on_hand", "reserved", "available")
    search_fields = ("variant__sku",)
    autocomplete_fields = ("variant", "warehouse")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("reference", "variant", "quantity", "status", "expires_at", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "variant__sku")
