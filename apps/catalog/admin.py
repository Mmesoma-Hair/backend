from __future__ import annotations

from django.contrib import admin

from .models import (
    Brand,
    Category,
    OptionType,
    OptionValue,
    Product,
    ProductImage,
    Variant,
    VariantOption,
)


class OptionTypeInline(admin.TabularInline):
    model = OptionType
    extra = 0


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ("public_id", "variant", "alt_text", "position", "is_primary")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "short_id", "category", "fulfillment_type", "is_active")
    list_filter = ("is_active", "fulfillment_type", "category")
    search_fields = ("title", "slug", "short_id")
    inlines = (OptionTypeInline, ProductImageInline)


class OptionValueInline(admin.TabularInline):
    model = OptionValue
    extra = 0


@admin.register(OptionType)
class OptionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "product", "position")
    search_fields = ("name", "product__title")
    inlines = (OptionValueInline,)


class VariantOptionInline(admin.TabularInline):
    model = VariantOption
    extra = 0
    autocomplete_fields = ("option_value",)


@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    list_display = ("sku", "product", "price", "is_default", "is_active", "fulfillment_type")
    list_filter = ("is_active", "is_default")
    search_fields = ("sku", "product__title", "barcode")
    inlines = (VariantOptionInline,)


@admin.register(OptionValue)
class OptionValueAdmin(admin.ModelAdmin):
    search_fields = ("value", "option_type__name")
    list_display = ("value", "option_type")
