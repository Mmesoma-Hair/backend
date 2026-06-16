from __future__ import annotations

from django.contrib import admin

from .models import Order, OrderLine


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0
    readonly_fields = ("variant", "sku", "title", "quantity", "line_total_charged")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "status",
        "owner",
        "paid_by_user",
        "currency",
        "total_charged",
        "created_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("number", "contact_email", "payer_email")
    inlines = (OrderLineInline,)
