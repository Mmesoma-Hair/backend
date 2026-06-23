"""Catalog domain models.

Two-level product model:

* ``Product`` — the conceptual item (title, description, category, brand, shared
  media). **Not directly sellable.**
* ``OptionType`` / ``OptionValue`` — named axes of variation (Size, Color) and
  their values (M, Red), stored as data so adding an axis never needs a migration.
* ``Variant`` — the sellable **SKU**: one specific combination of option values,
  carrying its own price, stock (via the inventory app), and fulfillment routing.
* ``VariantOption`` — through table mapping a variant to one value per option type.

Everything sellable is a ``Variant``; a "simple" product still gets exactly one
default variant, so cart/pricing/stock/orders never branch on "has variants?".
"""

from __future__ import annotations

import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from apps.common.models import BaseModel, TimeStampedModel


class FulfillmentType(models.TextChoices):
    INTERNAL = "internal", "Internal stock"
    DROPSHIP = "dropship", "Dropship supplier"


def _generate_short_id() -> str:
    """Short, URL-safe, unguessable id used in public share links (/p/<short_id>)."""
    return secrets.token_urlsafe(6)


class Category(TimeStampedModel):
    """Self-referential category tree (adjacency list)."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    position = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Cloudinary public_id of a representative image shown on the storefront.
    image_public_id = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("position", "name")
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Brand(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Product(BaseModel):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True)
    # Public, unguessable share handle. The canonical share URL is /p/<short_id>.
    short_id = models.CharField(
        max_length=16, unique=True, default=_generate_short_id, editable=False
    )
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    # Default routing for the product's variants (each variant may override).
    fulfillment_type = models.CharField(
        max_length=20, choices=FulfillmentType.choices, default=FulfillmentType.INTERNAL
    )
    # Default dropship supplier for the product's variants (each may override).
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    # When set, the product is grouped into the storefront "Flash Sale" section.
    is_flash_sale = models.BooleanField(default=False, db_index=True)
    # Product-level discount applied to every variant's price (0 = no discount).
    # The discounted price is what the customer is actually charged; the original
    # price is shown struck-through in the storefront.
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    # Key features / specs shown in the "Features" tab (Markdown).
    features = models.TextField(blank=True)
    # Denormalised review aggregates (kept current by the reviews service).
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0"))
    rating_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title

    @property
    def is_discounted(self) -> bool:
        return self.discount_percent is not None and self.discount_percent > 0

    def apply_discount(self, amount: Decimal) -> Decimal:
        """Apply this product's discount to a base amount (2dp, half-up)."""
        if not self.is_discounted:
            return amount
        factor = (Decimal("100") - self.discount_percent) / Decimal("100")
        return (amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = slugify(self.title) or "product"
        slug = base
        i = 2
        while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{i}"
            i += 1
        return slug


class OptionType(TimeStampedModel):
    """A named axis of variation for a product, e.g. Size or Color."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="option_types")
    name = models.CharField(max_length=60)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=["product", "name"], name="uniq_optiontype_per_product"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.product.title})"


class OptionValue(TimeStampedModel):
    option_type = models.ForeignKey(OptionType, on_delete=models.CASCADE, related_name="values")
    value = models.CharField(max_length=120)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["option_type", "value"], name="uniq_optionvalue_per_type"
            ),
        ]

    def __str__(self) -> str:
        return self.value


class Variant(BaseModel):
    """The sellable SKU — one specific combination of option values."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    # Base-currency price; the currency module converts for display/checkout.
    price = models.DecimalField(max_digits=12, decimal_places=2)
    # What we pay the supplier (base currency). For dropship variants this is set
    # by supplier sync; the selling price above = cost + the supplier's markup.
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    options = models.ManyToManyField(OptionValue, through="VariantOption", related_name="variants")
    # Deterministic fingerprint of the option-value combination, used to enforce
    # uniqueness within a product at the DB level (empty for a default variant).
    options_key = models.CharField(max_length=255, blank=True, default="", editable=False)

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    # Minimum order quantity (wholesale / MOQ selling). 1 = normal retail.
    moq = models.PositiveIntegerField(default=1)
    # Quantity price breaks: [{"min_qty": 50, "price": "1800.00"}, ...]. The unit
    # price for an order is the price of the highest min_qty tier <= the quantity
    # (falls back to ``price``). Sorted/validated by the admin serializer.
    price_tiers = models.JSONField(default=list, blank=True)
    weight_grams = models.PositiveIntegerField(null=True, blank=True)
    barcode = models.CharField(max_length=64, blank=True)
    # Override product routing per variant (blank = inherit from product).
    fulfillment_type = models.CharField(
        max_length=20, choices=FulfillmentType.choices, blank=True, default=""
    )
    # Override the dropship supplier per variant (null = inherit from product).
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="variants",
    )

    class Meta:
        ordering = ("product", "sku")
        constraints = [
            models.UniqueConstraint(
                fields=["product", "options_key"], name="uniq_variant_combination_per_product"
            ),
        ]

    def __str__(self) -> str:
        return self.sku

    def base_price_for(self, quantity: int) -> Decimal:
        """List unit price for ``quantity`` (before discount) — applies price breaks."""
        best = self.price
        best_min = 0
        for tier in self.price_tiers or []:
            try:
                tmin = int(tier.get("min_qty", 0))
                tprice = Decimal(str(tier.get("price")))
            except (TypeError, ValueError, ArithmeticError):
                continue
            if quantity >= tmin > best_min:
                best, best_min = tprice, tmin
        return best

    def unit_price_for(self, quantity: int) -> Decimal:
        """Base-currency unit price actually charged for ``quantity`` (after discount)."""
        return self.product.apply_discount(self.base_price_for(max(int(quantity or 1), 1)))

    @property
    def effective_price(self) -> Decimal:
        """Unit price at the MOQ — the realistic 'from' price for display."""
        return self.unit_price_for(self.moq or 1)

    @property
    def is_discounted(self) -> bool:
        return self.product.is_discounted

    @property
    def effective_fulfillment_type(self) -> str:
        return self.fulfillment_type or self.product.fulfillment_type

    @property
    def effective_supplier_id(self) -> int | None:
        return self.supplier_id or self.product.supplier_id

    @property
    def is_dropship(self) -> bool:
        return self.effective_fulfillment_type == FulfillmentType.DROPSHIP


class VariantOption(models.Model):
    """Maps a variant to exactly one option value per option type."""

    variant = models.ForeignKey(Variant, on_delete=models.CASCADE, related_name="variant_options")
    option_value = models.ForeignKey(
        OptionValue, on_delete=models.PROTECT, related_name="variant_options"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["variant", "option_value"], name="uniq_variant_optionvalue"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.variant.sku} → {self.option_value.value}"


class ProductImage(BaseModel):
    """A Cloudinary-backed image.

    Stores the Cloudinary ``public_id`` as the source of truth — never a raw file
    on the app server. A null ``variant`` means the image is product-level
    (shared); variant images take precedence and fall back to product images.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    variant = models.ForeignKey(
        Variant, null=True, blank=True, on_delete=models.CASCADE, related_name="images"
    )
    public_id = models.CharField(max_length=255)
    alt_text = models.CharField(max_length=255, blank=True)
    position = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ("position", "created_at")

    def __str__(self) -> str:
        return self.public_id


class ReviewStatus(models.TextChoices):
    PUBLISHED = "published", "Published"
    HIDDEN = "hidden", "Hidden"


class ProductReview(BaseModel):
    """A customer review for a product (one per user per product).

    ``is_verified_purchase`` is set when the author has a paid order containing
    the product. Admins can hide reviews (moderation); ``status`` drives whether
    a review is publicly visible and counts toward the product's rating.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="product_reviews",
    )
    author_name = models.CharField(max_length=120, blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=160, blank=True)
    body = models.TextField(blank=True)
    is_verified_purchase = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PUBLISHED, db_index=True
    )

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["product", "user"],
                condition=models.Q(user__isnull=False),
                name="uniq_review_per_user_product",
            )
        ]

    def __str__(self) -> str:
        return f"{self.rating}★ {self.product.title}"
