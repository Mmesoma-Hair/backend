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
from typing import BinaryIO

from django.conf import settings
from django.db import transaction

from apps.common.exceptions import ConflictError, DomainError

from .images import get_image_backend
from .models import (
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

    for index, combo in enumerate(itertools.product(*value_groups), start=1):
        ids = [v.id for v in combo]
        key = compute_options_key(ids)
        if key in existing_keys:
            continue
        variant = Variant.objects.create(
            product=product,
            sku=f"{prefix}-{index:03d}",
            price=default_price,
            options_key=key,
        )
        VariantOption.objects.bulk_create(
            [VariantOption(variant=variant, option_value=v) for v in combo]
        )
        existing_keys.add(key)
        created.append(variant)
    return created


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

    return ProductImage.objects.create(
        product=product,
        variant=variant,
        public_id=public_id,
        alt_text=alt_text,
        is_primary=is_primary,
        position=position,
    )


def upload_signature(extra_params: dict | None = None) -> dict:
    """Signed params for a client-side direct upload to Cloudinary."""
    params = {"folder": settings.CLOUDINARY_UPLOAD_FOLDER, **(extra_params or {})}
    return get_image_backend().signature(params)
