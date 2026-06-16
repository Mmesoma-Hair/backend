"""Discount engine.

Pure-ish computation over a cart's base-currency subtotal: validate coupons
against their conditions, compute each discount, then combine respecting
stackability. Amounts are in the store base currency; the cart layer converts
for display.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.utils import timezone

from apps.common.exceptions import DomainError

from .models import Coupon

TWO_PLACES = Decimal("0.01")


class CouponError(DomainError):
    default_code = "coupon_invalid"


@dataclass
class AppliedDiscount:
    code: str
    discount_type: str
    amount: Decimal  # base currency

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "type": self.discount_type, "amount": str(self.amount)}


def _has_prior_orders(user: Any) -> bool:
    """Whether the user has any non-cancelled orders (for first_order_only).

    Defensive: the orders app arrives in Phase 6; until then nobody has orders.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    related = getattr(user, "orders", None)
    if related is None:  # orders app not wired yet
        return False
    try:
        return related.exclude(status="cancelled").exists()
    except Exception:  # noqa: BLE001
        return False


def check_eligible(
    coupon: Coupon,
    *,
    subtotal: Decimal,
    category_subtotal: Decimal,
    user: Any = None,
    now=None,
) -> None:
    """Raise :class:`CouponError` if the coupon can't be applied."""
    now = now or timezone.now()
    if not coupon.is_active:
        raise CouponError(f"Coupon {coupon.code} is not active.", code="coupon_inactive")
    if coupon.valid_from and now < coupon.valid_from:
        raise CouponError(f"Coupon {coupon.code} is not yet valid.", code="coupon_not_started")
    if coupon.valid_until and now > coupon.valid_until:
        raise CouponError(f"Coupon {coupon.code} has expired.", code="coupon_expired")
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        raise CouponError(
            f"Coupon {coupon.code} has reached its usage limit.", code="coupon_exhausted"
        )
    if subtotal < coupon.min_spend:
        raise CouponError(
            f"Spend at least {coupon.min_spend} to use {coupon.code}.", code="coupon_min_spend"
        )
    if coupon.category_id is not None and category_subtotal <= 0:
        raise CouponError(
            f"Coupon {coupon.code} applies only to {coupon.category} items.",
            code="coupon_category",
        )
    if coupon.first_order_only and _has_prior_orders(user):
        raise CouponError(
            f"Coupon {coupon.code} is for first orders only.", code="coupon_first_order"
        )


def discount_amount(coupon: Coupon, *, subtotal: Decimal, category_subtotal: Decimal) -> Decimal:
    """The discount this coupon yields, in base currency (capped at the eligible base)."""
    eligible = category_subtotal if coupon.category_id is not None else subtotal
    if coupon.discount_type == Coupon.DiscountType.PERCENTAGE:
        raw = eligible * (coupon.value / Decimal("100"))
    else:
        raw = coupon.value
    raw = min(raw, eligible)
    return max(raw, Decimal("0")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_discounts(
    coupons: list[Coupon],
    *,
    subtotal: Decimal,
    category_subtotals: dict[int, Decimal],
    user: Any = None,
    now=None,
) -> dict[str, Any]:
    """Validate + combine coupon discounts, honouring stackability.

    If every applied coupon is stackable, their discounts sum (capped at the
    subtotal). If any is non-stackable, only the single best discount applies.
    """
    eligible: list[tuple[Coupon, Decimal]] = []
    for coupon in coupons:
        cat_sub = (
            category_subtotals.get(coupon.category_id, Decimal("0"))
            if coupon.category_id
            else subtotal
        )
        check_eligible(coupon, subtotal=subtotal, category_subtotal=cat_sub, user=user, now=now)
        eligible.append(
            (coupon, discount_amount(coupon, subtotal=subtotal, category_subtotal=cat_sub))
        )

    if not eligible:
        return {"applied": [], "total": Decimal("0.00")}

    all_stackable = all(c.stackable for c, _ in eligible)
    if all_stackable:
        applied = [AppliedDiscount(c.code, c.discount_type, amt) for c, amt in eligible]
    else:
        # Pick the single best discount.
        best = max(eligible, key=lambda pair: pair[1])
        applied = [AppliedDiscount(best[0].code, best[0].discount_type, best[1])]

    total = sum((d.amount for d in applied), Decimal("0"))
    total = min(total, subtotal).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return {"applied": [d.as_dict() for d in applied], "total": total}


def validate_code(code: str) -> Coupon:
    coupon = Coupon.objects.filter(code=code.strip().upper()).first()
    if coupon is None:
        raise CouponError(f"Unknown coupon code: {code}.", code="coupon_unknown")
    return coupon
