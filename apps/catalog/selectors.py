"""Catalog read/query logic."""

from __future__ import annotations

from django.db.models import Min, Prefetch, QuerySet

from .models import OptionValue, Product, Variant
from .services import compute_options_key


def active_products() -> QuerySet[Product]:
    return (
        Product.objects.filter(is_active=True)
        .select_related("category", "brand")
        .annotate(price_from=Min("variants__price"))
    )


def product_detail_queryset() -> QuerySet[Product]:
    """Products with everything the storefront detail view needs, prefetched."""
    return Product.objects.filter(is_active=True).prefetch_related(
        "option_types__values",
        Prefetch(
            "variants",
            queryset=Variant.objects.filter(is_active=True).prefetch_related("stock_items"),
        ),
        "variants__variant_options__option_value",
        "images",
    )


def get_product_by_slug(slug: str) -> Product | None:
    return product_detail_queryset().filter(slug=slug).first()


def get_product_by_share_handle(handle: str) -> Product | None:
    """Resolve a public share link by slug *or* short_id (both unauthenticated)."""
    qs = product_detail_queryset()
    return qs.filter(slug=handle).first() or qs.filter(short_id=handle).first()


def resolve_variant(product: Product, option_value_ids: list[int]) -> Variant | None:
    """Map a chosen combination of option values to its variant (or None)."""
    key = compute_options_key(option_value_ids)
    return product.variants.filter(is_active=True, options_key=key).first()


def variant_option_value_ids(variant: Variant) -> list[int]:
    return list(variant.variant_options.values_list("option_value_id", flat=True))


def option_values_for_product(product: Product) -> QuerySet[OptionValue]:
    return OptionValue.objects.filter(option_type__product=product)


def product_stock(product: Product) -> tuple[int, int]:
    """(available, full) units across the product's internal-stock variants.

    Relies on ``variants`` and ``variants__stock_items`` being prefetched, so it
    adds no queries inside a product list. Dropship variants (no owned stock) are
    excluded, so a dropship-only product reports (0, 0) and shows no stock bar.
    """
    available = full = 0
    for variant in product.variants.all():
        if variant.is_dropship:
            continue
        for item in variant.stock_items.all():
            available += max(item.on_hand - item.reserved, 0)
            full += item.full_stock
    return available, full
