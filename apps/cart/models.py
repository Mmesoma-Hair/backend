"""Cart and line items, plus the shareable "Pay for a Friend" link.

A cart belongs to a user *or* an anonymous session. Line items reference a
``catalog.Variant`` (the sellable unit) and snapshot the price at add-time so
price drift can be surfaced. Prices/stock are re-validated live, not trusted
from the snapshot.

A cart can be shared via an unguessable, revocable token with optional expiry —
anyone with the link can view it read-only and (Phase 6) pay on the owner's
behalf without ever seeing the owner's PII.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import Variant
from apps.common.models import BaseModel
from apps.promotions.models import Coupon


def generate_share_token() -> str:
    return secrets.token_urlsafe(24)


class Cart(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ORDERED = "ordered", "Ordered"
        ABANDONED = "abandoned", "Abandoned"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="carts",
    )
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    # Shopper's preferred display currency (totals can also be requested ad hoc).
    currency = models.CharField(max_length=3, blank=True)
    coupons = models.ManyToManyField(Coupon, blank=True, related_name="carts")

    # Pay-for-a-Friend share link.
    share_token = models.CharField(max_length=64, unique=True, null=True, blank=True, default=None)
    share_created_at = models.DateTimeField(null=True, blank=True)
    share_expires_at = models.DateTimeField(null=True, blank=True)
    share_revoked = models.BooleanField(default=False)
    allow_payer_to_set_shipping = models.BooleanField(default=False)
    # Shipping destination set by the owner (so a payer can't redirect goods).
    # Keys: name, line1, line2, city, region, postal_code, country, phone.
    shipping = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        who = self.owner.email if self.owner_id else f"session:{self.session_key[:8]}"
        return f"Cart<{who}>"

    @property
    def is_shared(self) -> bool:
        return bool(self.share_token) and not self.share_revoked

    @property
    def share_expired(self) -> bool:
        return self.share_expires_at is not None and timezone.now() > self.share_expires_at


class CartLine(BaseModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(Variant, on_delete=models.CASCADE, related_name="cart_lines")
    quantity = models.PositiveIntegerField(default=1)
    # Base-currency unit price captured when the item was added (drift detection).
    added_unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=["cart", "variant"], name="uniq_cartline_variant"),
        ]

    def __str__(self) -> str:
        return f"{self.variant.sku} x{self.quantity}"
