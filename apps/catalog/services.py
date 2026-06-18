"""Catalog business logic: variants, option combinations, images.

All mutation rules live here. The key invariants enforced:

* every product has exactly one default variant when it has no option types;
* a variant carries exactly one value per option type of its product;
* a combination of option values is unique within a product (DB-enforced via
  ``Variant.options_key``).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from decimal import Decimal
from typing import Any, BinaryIO

from django.conf import settings
from django.db import transaction

from apps.common.exceptions import ConflictError, DomainError

from .images import get_image_backend
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


def compute_options_key(option_value_ids: Iterable[int]) -> str:
    """Deterministic fingerprint of an option-value combination."""
    return "-".join(str(i) for i in sorted(set(option_value_ids)))


@transaction.atomic
def set_variant_options(variant: Variant, option_value_ids: list[int]) -> Variant:
    """Attach option values to a variant (one per option type) and lock its key.

    Validates that every value belongs to the product and that the values cover
    each option type exactly once, then enforces combination uniqueness.
    """
    values = list(OptionValue.objects.filter(id__in=option_value_ids).select_related("option_type"))
    if len(values) != len(set(option_value_ids)):
        raise DomainError("One or more option values do not exist.", code="invalid_option_value")

    product_option_type_ids = set(variant.product.option_types.values_list("id", flat=True))
    seen_types: set[int] = set()
    for value in values:
        if value.option_type_id not in product_option_type_ids:
            raise DomainError(
                "Option value does not belong to this product.", code="invalid_option_value"
            )
        if value.option_type_id in seen_types:
            raise DomainError(
                "A variant may have only one value per option type.",
                code="duplicate_option_type",
            )
        seen_types.add(value.option_type_id)

    if seen_types != product_option_type_ids:
        raise DomainError(
            "A variant must specify a value for every option type.", code="incomplete_options"
        )

    options_key = compute_options_key(option_value_ids)
    if (
        Variant.objects.filter(product=variant.product, options_key=options_key)
        .exclude(pk=variant.pk)
        .exists()
    ):
        raise ConflictError("A variant with this combination already exists.")

    variant.variant_options.all().delete()
    VariantOption.objects.bulk_create(
        [VariantOption(variant=variant, option_value=v) for v in values]
    )
    variant.options_key = options_key
    variant.is_default = False
    variant.save(update_fields=["options_key", "is_default", "updated_at"])
    return variant


@transaction.atomic
def ensure_default_variant(product: Product, *, sku: str, price: Decimal) -> Variant:
    """Create the single default variant for a simple (option-less) product."""
    if product.option_types.exists():
        raise DomainError(
            "Cannot create a default variant for a product that has option types.",
            code="has_options",
        )
    existing = product.variants.filter(is_default=True).first()
    if existing:
        return existing
    return Variant.objects.create(
        product=product, sku=sku, price=price, options_key="", is_default=True
    )


@transaction.atomic
def generate_variants(
    product: Product,
    *,
    default_price: Decimal,
    sku_prefix: str | None = None,
) -> list[Variant]:
    """Create variants for every combination of the product's option values.

    The cartesian product of values across option types. Combinations that
    already exist are skipped (idempotent), so admins can add an option value
    and regenerate to fill in the new combos.
    """
    option_types = list(product.option_types.prefetch_related("values").order_by("position", "id"))
    if not option_types:
        raise DomainError("Product has no option types to generate from.", code="no_options")

    value_groups = [list(ot.values.all()) for ot in option_types]
    if any(not group for group in value_groups):
        raise DomainError("Every option type needs at least one value.", code="empty_option_type")

    prefix = (sku_prefix or product.slug or "sku").upper().replace("-", "")[:12]
    created: list[Variant] = []
    existing_keys = set(product.variants.values_list("options_key", flat=True))

    # SKUs are globally unique. Track every SKU already using this prefix (across
    # all products + this product's earlier generations) and hand out the next
    # free number, so regenerating or reusing a prefix never collides.
    used_skus = set(
        Variant.objects.filter(sku__startswith=f"{prefix}-").values_list("sku", flat=True)
    )
    counter = 0

    def next_sku() -> str:
        nonlocal counter
        while True:
            counter += 1
            candidate = f"{prefix}-{counter:03d}"
            if candidate not in used_skus:
                used_skus.add(candidate)
                return candidate

    for combo in itertools.product(*value_groups):
        ids = [v.id for v in combo]
        key = compute_options_key(ids)
        if key in existing_keys:
            continue
        variant = Variant.objects.create(
            product=product,
            sku=next_sku(),
            price=default_price,
            options_key=key,
        )
        VariantOption.objects.bulk_create(
            [VariantOption(variant=variant, option_value=v) for v in combo]
        )
        existing_keys.add(key)
        created.append(variant)
    return created


@transaction.atomic
def create_product_full(
    *,
    title: str,
    description: str = "",
    category_id: int | None = None,
    new_category: str = "",
    brand_id: int | None = None,
    fulfillment_type: str = "internal",
    supplier_id: Any = None,
    is_active: bool = True,
    image_public_id: str = "",
    kind: str = "simple",
    sku: str | None = None,
    price: Decimal | None = None,
    stock: int = 0,
    options: list[dict] | None = None,
    default_price: Decimal | None = None,
    sku_prefix: str | None = None,
    stock_per_variant: int = 0,
) -> Product:
    """Create a product and everything it needs in ONE transaction.

    Either a simple product (one default variant) or a variable product (option
    types/values + a generated variant matrix), plus an optional featured image
    and starting stock. Because it's atomic, a failure anywhere (e.g. a SKU
    clash) rolls the whole thing back — so a retry never leaves orphan products.
    """
    # Local imports avoid any import cycle at module load.
    from django.utils.text import slugify

    from apps.inventory.services import set_stock

    category: Category | None = None
    if new_category.strip():
        name = new_category.strip()
        category, _ = Category.objects.get_or_create(
            slug=slugify(name) or name.lower(), defaults={"name": name}
        )
    elif category_id:
        category = Category.objects.filter(id=category_id).first()
    brand = Brand.objects.filter(id=brand_id).first() if brand_id else None
    supplier = None
    if supplier_id and fulfillment_type == "dropship":
        from apps.suppliers.models import Supplier

        supplier = Supplier.objects.filter(id=supplier_id).first()

    product = Product.objects.create(
        title=title.strip(),
        description=description.strip(),
        category=category,
        brand=brand,
        fulfillment_type=fulfillment_type,
        supplier=supplier,
        is_active=is_active,
    )

    if image_public_id.strip():
        add_product_image(
            product, public_id=image_public_id.strip(), alt_text=title.strip(), is_primary=True
        )

    if kind == "variable":
        for i, opt in enumerate(options or []):
            option_type = OptionType.objects.create(product=product, name=opt["name"], position=i)
            OptionValue.objects.bulk_create(
                [
                    OptionValue(option_type=option_type, value=val, position=j)
                    for j, val in enumerate(opt["values"])
                ]
            )
        variants = generate_variants(
            product, default_price=default_price or Decimal("0"), sku_prefix=sku_prefix or None
        )
        if stock_per_variant > 0:
            for variant in variants:
                set_stock(variant, stock_per_variant)
    else:
        variant = ensure_default_variant(product, sku=sku or "", price=price or Decimal("0"))
        if stock > 0:
            set_stock(variant, stock)

    return product


# --- images -----------------------------------------------------------------
@transaction.atomic
def add_product_image(
    product: Product,
    *,
    public_id: str | None = None,
    file: BinaryIO | bytes | str | None = None,
    variant: Variant | None = None,
    alt_text: str = "",
    is_primary: bool = False,
    position: int = 0,
) -> ProductImage:
    """Persist an image record.

    Either pass an already-uploaded ``public_id`` (the preferred signed-upload
    path, where the client uploads straight to Cloudinary) or raw ``file`` bytes
    to upload server-side through the backend.
    """
    if not public_id and file is None:
        raise DomainError("Provide either a public_id or a file to upload.", code="image_required")

    if not public_id:
        backend = get_image_backend()
        public_id = backend.upload(file, folder=settings.CLOUDINARY_UPLOAD_FOLDER)

    if variant is not None and variant.product_id != product.id:
        raise DomainError("Variant does not belong to this product.", code="variant_mismatch")

    # One image per variant: a new variant image replaces the old one.
    if variant is not None:
        ProductImage.objects.filter(product=product, variant=variant).delete()

    image = ProductImage.objects.create(
        product=product,
        variant=variant,
        public_id=public_id,
        alt_text=alt_text,
        is_primary=is_primary,
        position=position,
    )
    # A product has a single featured (primary) product-level image.
    if is_primary and variant is None:
        _unset_other_primaries(image)
    return image


def _unset_other_primaries(image: ProductImage) -> None:
    ProductImage.objects.filter(
        product_id=image.product_id, variant__isnull=True, is_primary=True
    ).exclude(id=image.id).update(is_primary=False)


def set_primary_image(image: ProductImage) -> ProductImage:
    """Make ``image`` the product's featured image; unset the others."""
    if not image.is_primary:
        image.is_primary = True
        image.save(update_fields=["is_primary", "updated_at"])
    _unset_other_primaries(image)
    return image


def upload_signature(extra_params: dict | None = None) -> dict:
    """Signed params for a client-side direct upload to Cloudinary."""
    params = {"folder": settings.CLOUDINARY_UPLOAD_FOLDER, **(extra_params or {})}
    return get_image_backend().signature(params)
