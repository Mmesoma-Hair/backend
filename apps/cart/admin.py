from __future__ import annotations

from django.contrib import admin

from .models import Cart, CartLine


class CartLineInline(admin.TabularInline):
    model = CartLine
    extra = 0
    autocomplete_fields = ("variant",)


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "session_key", "status", "is_shared", "created_at")
    list_filter = ("status", "share_revoked")
    search_fields = ("owner__email", "session_key", "share_token")
    inlines = (CartLineInline,)
