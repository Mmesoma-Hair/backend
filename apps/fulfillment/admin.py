from __future__ import annotations

from django.contrib import admin

from .models import Shipment, ShipmentLine, SupplierOrder


class ShipmentLineInline(admin.TabularInline):
    model = ShipmentLine
    extra = 0


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("order", "kind", "status", "warehouse", "supplier", "tracking_number")
    list_filter = ("kind", "status")
    search_fields = ("order__number", "tracking_number")
    inlines = (ShipmentLineInline,)


@admin.register(SupplierOrder)
class SupplierOrderAdmin(admin.ModelAdmin):
    list_display = ("external_ref", "order", "supplier", "status")
    list_filter = ("status", "supplier")
    search_fields = ("external_ref", "order__number")
