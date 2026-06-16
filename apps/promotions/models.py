"""Coupons and discount rules.

A coupon carries a discount (percentage or fixed) plus optional conditions
(min spend, a category restriction, first-order-only) and a stackability flag.
The discount engine in :mod:`apps.promotions.services` evaluates these against a
cart subtotal; coupons never mutate carts or prices themselves.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.common.models import TimeStampedModel


class Coupon(TimeStampedModel):
    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage"
        FIXED = "fixed", "Fixed amount"

    code = models.CharField(max_length=40, unique=True)
    description = models.CharField(max_length=255, blank=True)
    discount_type = models.CharField(max_length=12, choices=DiscountType.choices)
    # For percentage: 0–100. For fixed: an amount in the store base currency.
    value = models.DecimalField(max_digits=12, decimal_places=2)

    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    # Conditions.
    min_spend = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    category = models.ForeignKey(
        "catalog.Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="coupons",
        help_text="If set, the discount applies only to items in this category.",
    )
    first_order_only = models.BooleanField(default=False)

    # Stackability + usage limits.
    stackable = models.BooleanField(default=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("code",)

    def __str__(self) -> str:
        return self.code

    def save(self, *args: object, **kwargs: object) -> None:
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)
