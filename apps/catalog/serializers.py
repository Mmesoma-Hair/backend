"""Public storefront serializers (read-only).

These never accept writes — admin mutations use ``admin_serializers`` so the two
surfaces can diverge safely. Images are exposed as derived Cloudinary URLs
(``f_auto``/``q_auto`` size variants), never as bare public_ids.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.currency.pricing import price_for
from apps.inventory.selectors import variant_availability

from .images import image_urls
from .models import Brand, Category, OptionType, OptionValue, Product, ProductImage, Variant


def _ctx_currency(serializer: serializers.Serializer) -> str | None:
    return serializer.context.get("currency") if serializer.context else None


class ProductImageSerializer(serializers.ModelSerializer):
    urls = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ("id", "alt_text", "position", "is_primary", "variant", "urls")

    def get_urls(self, obj: ProductImage) -> dict[str, str]:
        return image_urls(obj.public_id)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug", "parent", "position")


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ("id", "name", "slug")


class OptionValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionValue
        fields = ("id", "value", "position")


class OptionTypeSerializer(serializers.ModelSerializer):
    values = OptionValueSerializer(many=True, read_only=True)

    class Meta:
        model = OptionType
        fields = ("id", "name", "position", "values")


class VariantSerializer(serializers.ModelSerializer):
    option_value_ids = serializers.SerializerMethodField()
    fulfillment_type = serializers.CharField(source="effective_fulfillment_type", read_only=True)
    available = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    images = ProductImageSerializer(many=True, read_only=True)
    price_display = serializers.SerializerMethodField()

    class Meta:
        model = Variant
        fields = (
            "id",
            "sku",
            "price",
            "price_display",
            "is_default",
            "options_key",
            "option_value_ids",
            "fulfillment_type",
            "available",
            "in_stock",
            "images",
        )

    def get_price_display(self, obj: Variant) -> dict | None:
        currency = _ctx_currency(self)
        return price_for(obj.price, currency) if currency else None

    def get_option_value_ids(self, obj: Variant) -> list[int]:
        # Uses prefetched variant_options to avoid an extra query per variant.
        return [vo.option_value_id for vo in obj.variant_options.all()]

    def get_available(self, obj: Variant) -> int:
        return variant_availability(obj)

    def get_in_stock(self, obj: Variant) -> bool:
        return variant_availability(obj) > 0


class ProductListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    price_from = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    price_from_display = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    share_path = serializers.SerializerMethodField()
    has_options = serializers.SerializerMethodField()
    default_variant = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "title",
            "slug",
            "short_id",
            "category",
            "brand",
            "price_from",
            "price_from_display",
            "primary_image",
            "share_path",
            "has_options",
            "default_variant",
        )

    def get_has_options(self, obj: Product) -> bool:
        return len(obj.option_types.all()) > 0

    def get_default_variant(self, obj: Product) -> str | None:
        """Variant a card can add directly (the default / only one)."""
        variants = list(obj.variants.all())
        if not variants:
            return None
        chosen = next((v for v in variants if v.is_default), None) or variants[0]
        return str(chosen.id)

    def get_price_from_display(self, obj: Product) -> dict | None:
        currency = _ctx_currency(self)
        return price_for(getattr(obj, "price_from", None), currency) if currency else None

    def get_primary_image(self, obj: Product) -> dict[str, Any] | None:
        images = (
            list(obj.images.all())
            if hasattr(obj, "_prefetched_objects_cache")
            else obj.images.all()
        )
        chosen = next((i for i in images if i.is_primary), None) or (images[0] if images else None)
        return image_urls(chosen.public_id) if chosen else None

    def get_share_path(self, obj: Product) -> str:
        return f"/p/{obj.short_id}"


class ProductDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    option_types = OptionTypeSerializer(many=True, read_only=True)
    variants = VariantSerializer(many=True, read_only=True)
    images = serializers.SerializerMethodField()
    share_path = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "title",
            "slug",
            "short_id",
            "description",
            "category",
            "brand",
            "fulfillment_type",
            "option_types",
            "variants",
            "images",
            "share_path",
        )

    def get_images(self, obj: Product) -> list[dict[str, Any]]:
        # Product-level (shared) images only; variant images live on each variant.
        product_images = [i for i in obj.images.all() if i.variant_id is None]
        return ProductImageSerializer(product_images, many=True).data

    def get_share_path(self, obj: Product) -> str:
        return f"/p/{obj.short_id}"


class ResolveVariantRequestSerializer(serializers.Serializer):
    option_value_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)
