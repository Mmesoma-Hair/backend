"""Admin write serializers (separate from the public read serializers)."""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    Brand,
    Category,
    OptionType,
    OptionValue,
    Product,
    Variant,
)


class CategoryAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug", "parent", "position", "is_active")
        extra_kwargs = {"slug": {"required": False}}

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("slug") and attrs.get("name"):
            from django.utils.text import slugify

            attrs["slug"] = slugify(attrs["name"])
        return attrs


class BrandAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ("id", "name", "slug", "is_active")
        extra_kwargs = {"slug": {"required": False}}

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("slug") and attrs.get("name"):
            from django.utils.text import slugify

            attrs["slug"] = slugify(attrs["name"])
        return attrs


class ProductAdminSerializer(serializers.ModelSerializer):
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
            "is_active",
        )
        read_only_fields = ("short_id",)
        extra_kwargs = {"slug": {"required": False}}


class OptionTypeAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionType
        fields = ("id", "product", "name", "position")


class OptionValueAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionValue
        fields = ("id", "option_type", "value", "position")


class VariantAdminSerializer(serializers.ModelSerializer):
    # Optional: set the variant's option-value combination on write.
    option_value_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )

    class Meta:
        model = Variant
        fields = (
            "id",
            "product",
            "sku",
            "price",
            "is_active",
            "is_default",
            "weight_grams",
            "barcode",
            "fulfillment_type",
            "options_key",
            "option_value_ids",
        )
        read_only_fields = ("options_key", "is_default")


class ProductImageCreateSerializer(serializers.Serializer):
    """Create an image record from an already-uploaded Cloudinary public_id."""

    public_id = serializers.CharField()
    variant = serializers.PrimaryKeyRelatedField(
        queryset=Variant.objects.all(), required=False, allow_null=True
    )
    alt_text = serializers.CharField(required=False, allow_blank=True, default="")
    position = serializers.IntegerField(required=False, default=0)
    is_primary = serializers.BooleanField(required=False, default=False)


class GenerateVariantsSerializer(serializers.Serializer):
    default_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    sku_prefix = serializers.CharField(required=False, allow_blank=True)


class UploadSignatureSerializer(serializers.Serializer):
    """Empty request; returns signed params for a direct client upload."""
