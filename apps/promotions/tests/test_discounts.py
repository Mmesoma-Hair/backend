from __future__ import annotations

from decimal import Decimal

import pytest

from apps.promotions import services
from apps.promotions.models import Coupon
from apps.promotions.services import CouponError


def _coupon(**kwargs) -> Coupon:
    defaults = {
        "code": "X",
        "discount_type": Coupon.DiscountType.PERCENTAGE,
        "value": Decimal("10"),
    }
    defaults.update(kwargs)
    return Coupon.objects.create(**defaults)


@pytest.mark.django_db
def test_percentage_discount() -> None:
    c = _coupon(code="P10", value=Decimal("10"))
    out = services.compute_discounts([c], subtotal=Decimal("100"), category_subtotals={})
    assert out["total"] == Decimal("10.00")


@pytest.mark.django_db
def test_fixed_discount_capped_at_subtotal() -> None:
    c = _coupon(code="F50", discount_type=Coupon.DiscountType.FIXED, value=Decimal("50"))
    out = services.compute_discounts([c], subtotal=Decimal("30"), category_subtotals={})
    assert out["total"] == Decimal("30.00")


@pytest.mark.django_db
def test_min_spend_not_met_raises() -> None:
    c = _coupon(code="MIN", min_spend=Decimal("100"))
    with pytest.raises(CouponError):
        services.compute_discounts([c], subtotal=Decimal("50"), category_subtotals={})


@pytest.mark.django_db
def test_stackable_coupons_sum() -> None:
    a = _coupon(code="A", value=Decimal("10"), stackable=True)
    b = _coupon(
        code="B", discount_type=Coupon.DiscountType.FIXED, value=Decimal("5"), stackable=True
    )
    out = services.compute_discounts([a, b], subtotal=Decimal("100"), category_subtotals={})
    assert out["total"] == Decimal("15.00")  # 10 + 5


@pytest.mark.django_db
def test_non_stackable_picks_best() -> None:
    a = _coupon(code="A", value=Decimal("10"), stackable=True)  # 10
    b = _coupon(
        code="B", discount_type=Coupon.DiscountType.FIXED, value=Decimal("25"), stackable=False
    )  # 25
    out = services.compute_discounts([a, b], subtotal=Decimal("100"), category_subtotals={})
    assert out["total"] == Decimal("25.00")
    assert len(out["applied"]) == 1


@pytest.mark.django_db
def test_expired_coupon_rejected() -> None:
    from datetime import timedelta

    from django.utils import timezone

    c = _coupon(code="OLD", valid_until=timezone.now() - timedelta(days=1))
    with pytest.raises(CouponError):
        services.compute_discounts([c], subtotal=Decimal("100"), category_subtotals={})


@pytest.mark.django_db
def test_max_uses_exhausted_rejected() -> None:
    c = _coupon(code="LIMIT", max_uses=1, used_count=1)
    with pytest.raises(CouponError):
        services.compute_discounts([c], subtotal=Decimal("100"), category_subtotals={})


@pytest.mark.django_db
def test_unknown_code_raises() -> None:
    with pytest.raises(CouponError):
        services.validate_code("NOPE")
