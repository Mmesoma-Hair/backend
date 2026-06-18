"""Admin write serializers (separate from the public read serializers)."""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    Brand,
    Category,
    FulfillmentType,
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
    primary_image = serializers.SerializerMethodField()
    variant_count = serializers.SerializerMethodField()
    price_from = serializers.SerializerMethodField()

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
            "supplier",
            "is_active",
            "primary_image",
            "variant_count",
            "price_from",
        )
        read_only_fields = ("short_id", "primary_image", "variant_count", "price_from")
        extra_kwargs = {"slug": {"required": False}, "supplier": {"required": False}}

    def get_primary_image(self, obj: Product) -> str | None:
        from .images import image_urls

        images = [i for i in obj.images.all() if i.variant_id is None]
        chosen = next((i for i in images if i.is_primary), None) or (images[0] if images else None)
        return image_urls(chosen.public_id)["card"] if chosen else None

    def get_variant_count(self, obj: Product) -> int:
        return len(obj.variants.all())

    def get_price_from(self, obj: Product) -> str | None:
        prices = [v.price for v in obj.variants.all()]
        return str(min(prices)) if prices else None


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
            "cost_price",
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


class _OptionInputSerializer(serializers.Serializer):
    name = serializers.CharField()
    values = serializers.ListField(child=serializers.CharField(allow_blank=True))


class ProductCreateSerializer(serializers.Serializer):
    """Full, atomic product creation: details + image + (simple|variable) + stock."""

    title = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default="")
    category = serializers.IntegerField(required=False, allow_null=True)
    new_category = serializers.CharField(required=False, allow_blank=True, default="")
    brand = serializers.IntegerField(required=False, allow_null=True)
    fulfillment_type = serializers.ChoiceField(
        choices=[c[0] for c in FulfillmentType.choices], default=FulfillmentType.INTERNAL
    )
    supplier = serializers.IntegerField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)
    image_public_id = serializers.CharField(required=False, allow_blank=True, default="")

    kind = serializers.ChoiceField(choices=["simple", "variable"])
    # simple
    sku = serializers.CharField(required=False, allow_blank=True, default="")
    price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    stock = serializers.IntegerField(required=False, default=0, min_value=0)
    # variable
    options = _OptionInputSerializer(many=True, required=False)
    default_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    sku_prefix = serializers.CharField(required=False, allow_blank=True, default="")
    stock_per_variant = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate(self, attrs: dict) -> dict:
        if attrs["kind"] == "simple":
            if not attrs.get("sku", "").strip() or attrs.get("price") is None:
                raise serializers.ValidationError(
                    "SKU and price are required for a simple product."
                )
        else:
            cleaned = []
            for opt in attrs.get("options", []):
                name = opt["name"].strip()
                values = [v.strip() for v in opt["values"] if v.strip()]
                if name and values:
                    cleaned.append({"name": name, "values": values})
            if not cleaned:
                raise serializers.ValidationError(
                    "Add at least one option with at least one value."
                )
            if attrs.get("default_price") is None:
                raise serializers.ValidationError(
                    "A default price is required to generate variants."
                )
            attrs["options"] = cleaned
        return attrs
