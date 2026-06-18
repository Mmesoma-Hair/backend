"""Cart read logic: lookup, validation, and currency-aware totals."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import QuerySet

from apps.catalog.images import image_urls
from apps.catalog.models import Product
from apps.currency import selectors as currency_selectors
from apps.currency import services as currency_services
from apps.inventory.selectors import variant_availability
from apps.promotions import services as promo_services

from .models import Cart, CartLine


def get_active_cart(*, user: Any = None, session_key: str = "") -> Cart | None:
    qs = Cart.objects.filter(status=Cart.Status.ACTIVE)
    if user is not None and getattr(user, "is_authenticated", False):
        return qs.filter(owner=user).first()
    if session_key:
        return qs.filter(owner__isnull=True, session_key=session_key).first()
    return None


def cart_lines(cart: Cart) -> QuerySet[CartLine]:
    return cart.lines.select_related(
        "variant", "variant__product", "variant__product__category"
    ).prefetch_related("variant__product__images")


def _primary_image_url(product: Product) -> str | None:
    """Card-size URL of a product's primary (product-level) image, if any."""
    images = [i for i in product.images.all() if i.variant_id is None]
    chosen = next((i for i in images if i.is_primary), None) or (images[0] if images else None)
    return image_urls(chosen.public_id)["card"] if chosen else None


def validate_cart(cart: Cart) -> list[dict[str, Any]]:
    """Live stock/price/availability checks. Returns a list of issues (empty = OK)."""
    issues: list[dict[str, Any]] = []
    for line in cart_lines(cart):
        variant = line.variant
        if not variant.is_active:
            issues.append({"line": str(line.id), "sku": variant.sku, "code": "inactive"})
            continue
        available = variant_availability(variant)
        if available < line.quantity:
            issues.append(
                {
                    "line": str(line.id),
                    "sku": variant.sku,
                    "code": "insufficient_stock",
                    "available": available,
                    "requested": line.quantity,
                }
            )
        if variant.effective_price != line.added_unit_price:
            issues.append(
                {
                    "line": str(line.id),
                    "sku": variant.sku,
                    "code": "price_changed",
                    "was": str(line.added_unit_price),
                    "now": str(variant.effective_price),
                }
            )
    return issues


def _money(base_amount: Decimal, currency_code: str) -> dict[str, Any]:
    return currency_services.price_quote(base_amount, currency_code)


def compute_cart_totals(cart: Cart, *, currency: str | None = None) -> dict[str, Any]:
    """Currency-aware cart totals with discounts applied to the base subtotal."""
    base = currency_selectors.base_code()
    display = (currency or cart.currency or base).upper()
    if display not in set(currency_selectors.active_codes()):
        display = base

    lines_out: list[dict[str, Any]] = []
    subtotal = Decimal("0")
    category_subtotals: dict[int, Decimal] = {}

    for line in cart_lines(cart):
        unit = line.variant.effective_price
        line_base = unit * line.quantity
        subtotal += line_base
        cat_id = line.variant.product.category_id
        if cat_id is not None:
            category_subtotals[cat_id] = category_subtotals.get(cat_id, Decimal("0")) + line_base
        lines_out.append(
            {
                "id": str(line.id),
                "variant": str(line.variant_id),
                "sku": line.variant.sku,
                "product_title": line.variant.product.title,
                "product_slug": line.variant.product.slug,
                "image": _primary_image_url(line.variant.product),
                "quantity": line.quantity,
                "unit_price": _money(unit, display),
                "line_total": _money(line_base, display),
                "price_changed": unit != line.added_unit_price,
                "in_stock": variant_availability(line.variant) >= line.quantity,
            }
        )

    discounts = promo_services.compute_discounts(
        list(cart.coupons.all()),
        subtotal=subtotal,
        category_subtotals=category_subtotals,
        user=cart.owner,
    )
    discount_total = discounts["total"]
    total = max(subtotal - discount_total, Decimal("0"))

    return {
        "currency": display,
        "base_currency": base,
        "lines": lines_out,
        "subtotal": _money(subtotal, display),
        "discounts": {
            "applied": [
                {**d, "amount_display": _money(Decimal(d["amount"]), display)}
                for d in discounts["applied"]
            ],
            "total": _money(discount_total, display),
        },
        "total": _money(total, display),
        "item_count": sum(line.quantity for line in cart.lines.all()),
    }
