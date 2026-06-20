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
from .models import (
    Brand,
    Category,
    OptionType,
    OptionValue,
    Product,
    ProductImage,
    ProductReview,
    Variant,
)


class ProductReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductReview
        fields = (
            "id",
            "author_name",
            "rating",
            "title",
            "body",
            "is_verified_purchase",
            "created_at",
        )


class ReviewCreateSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    title = serializers.CharField(required=False, allow_blank=True, default="", max_length=160)
    body = serializers.CharField(required=False, allow_blank=True, default="")
    author_name = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=120
    )


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
    # `price`/`price_display` are what the customer pays (after any discount);
    # `compare_at_display` is the original (struck-through) price when discounted.
    price = serializers.DecimalField(
        source="effective_price", max_digits=12, decimal_places=2, read_only=True
    )
    price_display = serializers.SerializerMethodField()
    compare_at_display = serializers.SerializerMethodField()
    discount_percent = serializers.DecimalField(
        source="product.discount_percent", max_digits=5, decimal_places=2, read_only=True
    )
    price_tiers = serializers.SerializerMethodField()

    class Meta:
        model = Variant
        fields = (
            "id",
            "sku",
            "price",
            "price_display",
            "compare_at_display",
            "discount_percent",
            "moq",
            "price_tiers",
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
        return price_for(obj.effective_price, currency) if currency else None

    def get_price_tiers(self, obj: Variant) -> list[dict]:
        """Quantity price breaks with the (discounted) unit price for each tier."""
        currency = _ctx_currency(self)
        out: list[dict] = []
        for tier in obj.price_tiers or []:
            try:
                min_qty = int(tier.get("min_qty", 0))
            except (TypeError, ValueError):
                continue
            unit = obj.unit_price_for(min_qty)
            out.append(
                {
                    "min_qty": min_qty,
                    "unit_price": str(unit),
                    "unit_price_display": price_for(unit, currency) if currency else None,
                }
            )
        out.sort(key=lambda t: t["min_qty"])
        return out

    def get_compare_at_display(self, obj: Variant) -> dict | None:
        currency = _ctx_currency(self)
        if not currency or not obj.is_discounted:
            return None
        return price_for(obj.price, currency)

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
    price_from = serializers.SerializerMethodField()
    price_from_display = serializers.SerializerMethodField()
    compare_at_from_display = serializers.SerializerMethodField()
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    rating_avg = serializers.DecimalField(max_digits=3, decimal_places=2, read_only=True)
    rating_count = serializers.IntegerField(read_only=True)
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
            "compare_at_from_display",
            "discount_percent",
            "rating_avg",
            "rating_count",
            "primary_image",
            "share_path",
            "has_options",
            "default_variant",
        )

    def _orig_price_from(self, obj: Product) -> Any:
        return getattr(obj, "price_from", None)

    def get_price_from(self, obj: Product) -> str | None:
        original = self._orig_price_from(obj)
        return str(obj.apply_discount(original)) if original is not None else None

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
        original = self._orig_price_from(obj)
        if not currency or original is None:
            return None
        return price_for(obj.apply_discount(original), currency)

    def get_compare_at_from_display(self, obj: Product) -> dict | None:
        currency = _ctx_currency(self)
        original = self._orig_price_from(obj)
        if not currency or original is None or not obj.is_discounted:
            return None
        return price_for(original, currency)

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
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    rating_avg = serializers.DecimalField(max_digits=3, decimal_places=2, read_only=True)
    rating_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "title",
            "slug",
            "short_id",
            "description",
            "features",
            "category",
            "brand",
            "fulfillment_type",
            "discount_percent",
            "rating_avg",
            "rating_count",
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
