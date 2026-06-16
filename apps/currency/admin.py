from __future__ import annotations

from django.contrib import admin

from .models import Currency, ExchangeRate


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "symbol",
        "decimal_places",
        "rounding_increment",
        "charm_pricing",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("base", "quote", "rate", "source", "fetched_at")
    list_filter = ("base", "source")
    search_fields = ("quote",)
