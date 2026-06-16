from __future__ import annotations

from django.contrib import admin

from .models import Coupon


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_type",
        "value",
        "is_active",
        "stackable",
        "min_spend",
        "used_count",
        "max_uses",
    )
    list_filter = ("discount_type", "is_active", "stackable")
    search_fields = ("code", "description")
