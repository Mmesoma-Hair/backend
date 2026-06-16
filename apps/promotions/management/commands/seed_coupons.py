"""Seed a couple of demo coupons."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand

from apps.promotions.models import Coupon


class Command(BaseCommand):
    help = "Seed demo coupons (WELCOME10 percentage, SAVE5 fixed)."

    def handle(self, *args: Any, **options: Any) -> None:
        Coupon.objects.update_or_create(
            code="WELCOME10",
            defaults={
                "description": "10% off your order",
                "discount_type": Coupon.DiscountType.PERCENTAGE,
                "value": Decimal("10"),
                "stackable": True,
            },
        )
        Coupon.objects.update_or_create(
            code="SAVE5",
            defaults={
                "description": "$5 off orders over $25",
                "discount_type": Coupon.DiscountType.FIXED,
                "value": Decimal("5"),
                "min_spend": Decimal("25"),
                "stackable": False,
            },
        )
        self.stdout.write(self.style.SUCCESS("Seeded coupons: WELCOME10, SAVE5"))
