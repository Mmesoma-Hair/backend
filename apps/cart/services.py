"""Cart business logic: items, coupons, and the shareable link."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Variant
from apps.common.exceptions import DomainError, GoneError
from apps.promotions import services as promo_services
from apps.storeconfig.selectors import get_setting

from .models import Cart, CartLine, generate_share_token


@transaction.atomic
def get_or_create_cart(*, user: Any = None, session_key: str = "") -> Cart:
    if user is not None and getattr(user, "is_authenticated", False):
        cart, _ = Cart.objects.get_or_create(
            owner=user, status=Cart.Status.ACTIVE, defaults={"session_key": session_key}
        )
        return cart
    if not session_key:
        raise DomainError("A session is required for an anonymous cart.", code="no_session")
    cart, _ = Cart.objects.get_or_create(
        owner__isnull=True, session_key=session_key, status=Cart.Status.ACTIVE
    )
    return cart


def _active_variant(variant_id: str) -> Variant:
    variant = Variant.objects.filter(id=variant_id, is_active=True).first()
    if variant is None:
        raise DomainError("That product variant is unavailable.", code="variant_unavailable")
    return variant


@transaction.atomic
def add_item(cart: Cart, *, variant_id: str, quantity: int = 1) -> CartLine:
    if quantity <= 0:
        raise DomainError("Quantity must be positive.", code="invalid_quantity")
    variant = _active_variant(variant_id)
    line = cart.lines.filter(variant=variant).first()
    new_qty = (line.quantity if line else 0) + quantity
    # Enforce the minimum order quantity (wholesale / MOQ).
    new_qty = max(new_qty, variant.moq or 1)
    if line is None:
        line = CartLine(cart=cart, variant=variant, quantity=0)
    line.quantity = new_qty
    # Quantity-aware unit price (price breaks + discount).
    line.added_unit_price = variant.unit_price_for(new_qty)
    line.save()
    return line


@transaction.atomic
def update_item(cart: Cart, *, line_id: str, quantity: int) -> CartLine | None:
    line = cart.lines.filter(id=line_id).first()
    if line is None:
        raise DomainError("Cart line not found.", code="line_not_found")
    if quantity <= 0:
        line.delete()
        return None
    # Never below the variant's MOQ.
    line.quantity = max(quantity, line.variant.moq or 1)
    line.added_unit_price = line.variant.unit_price_for(line.quantity)
    line.save(update_fields=["quantity", "added_unit_price", "updated_at"])
    return line


@transaction.atomic
def remove_item(cart: Cart, *, line_id: str) -> None:
    deleted, _ = cart.lines.filter(id=line_id).delete()
    if not deleted:
        raise DomainError("Cart line not found.", code="line_not_found")


@transaction.atomic
def apply_coupon(cart: Cart, *, code: str) -> None:
    coupon = promo_services.validate_code(code)
    # Surface obvious problems early (full re-check happens at total computation).
    if not coupon.is_active:
        raise promo_services.CouponError(
            f"Coupon {coupon.code} is not active.", code="coupon_inactive"
        )
    cart.coupons.add(coupon)


SHIPPING_FIELDS = {"name", "line1", "line2", "city", "region", "postal_code", "country", "phone"}


@transaction.atomic
def set_shipping(cart: Cart, data: dict) -> Cart:
    """Set the owner's shipping destination on the cart."""
    cart.shipping = {k: v for k, v in data.items() if k in SHIPPING_FIELDS and v}
    cart.save(update_fields=["shipping", "updated_at"])
    return cart


@transaction.atomic
def remove_coupon(cart: Cart, *, code: str) -> None:
    coupon = cart.coupons.filter(code=code.strip().upper()).first()
    if coupon:
        cart.coupons.remove(coupon)


# --- Pay for a Friend share link -------------------------------------------
@transaction.atomic
def create_share(cart: Cart, *, expires_in_hours: int | None = None) -> Cart:
    if not get_setting("features.pay_for_a_friend"):
        raise DomainError("Sharing carts is disabled.", code="feature_disabled")
    if not cart.share_token or cart.share_revoked:
        cart.share_token = generate_share_token()
    cart.share_revoked = False
    cart.share_created_at = timezone.now()
    cart.share_expires_at = (
        timezone.now() + timedelta(hours=expires_in_hours) if expires_in_hours else None
    )
    cart.allow_payer_to_set_shipping = bool(get_setting("features.allow_payer_to_set_shipping"))
    cart.save(
        update_fields=[
            "share_token",
            "share_revoked",
            "share_created_at",
            "share_expires_at",
            "allow_payer_to_set_shipping",
            "updated_at",
        ]
    )
    return cart


@transaction.atomic
def revoke_share(cart: Cart) -> None:
    cart.share_revoked = True
    cart.save(update_fields=["share_revoked", "updated_at"])


def resolve_shared_cart(token: str) -> Cart:
    """Resolve a share token to its cart.

    404 (DoesNotExist surfaced by the view) if unknown; **410 Gone** if the link
    was revoked or has expired.
    """
    cart = Cart.objects.filter(share_token=token).first()
    if cart is None:
        raise Cart.DoesNotExist
    if cart.share_revoked:
        raise GoneError("This shared cart link has been revoked.", code="share_revoked")
    if cart.share_expired:
        raise GoneError("This shared cart link has expired.", code="share_expired")
    return cart
