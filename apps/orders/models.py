"""Orders: the order, its lines, and the status state machine.

An order records its **owner** (the cart creator) and, when paid through a
shared "Pay for a Friend" link, the **payer** (a different user or a guest) —
separately, so paying never transfers ownership. Money is stored in both the
store base currency and the charged currency, with the FX rate locked at
checkout so the charge (and any later refund) is deterministic.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models

from apps.catalog.models import Variant
from apps.common.models import BaseModel


def generate_order_number() -> str:
    return f"IC-{secrets.token_hex(4).upper()}"


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending payment"
    PAID = "paid", "Paid"
    ROUTING = "routing", "Routing"
    PARTIALLY_FULFILLED = "partially_fulfilled", "Partially fulfilled"
    FULFILLED = "fulfilled", "Fulfilled"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"


class Order(BaseModel):
    number = models.CharField(
        max_length=20, unique=True, default=generate_order_number, editable=False
    )
    status = models.CharField(
        max_length=24, choices=OrderStatus.choices, default=OrderStatus.PENDING, db_index=True
    )

    # Ownership: the cart creator. Null for a guest-owned cart (contact snapshot kept).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    contact_email = models.EmailField(blank=True)
    contact_name = models.CharField(max_length=255, blank=True)

    # Payer identity (Pay for a Friend) — who paid, recorded without changing ownership.
    paid_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="paid_orders",
    )
    payer_email = models.EmailField(blank=True)
    payer_name = models.CharField(max_length=255, blank=True)

    # Currency + locked FX rate (1 base = fx_rate_locked × currency).
    base_currency = models.CharField(max_length=3)
    currency = models.CharField(max_length=3)
    fx_rate_locked = models.DecimalField(max_digits=20, decimal_places=10, default=1)

    # Money — base currency.
    subtotal_base = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_base = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_base = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Money — charged currency (using the locked rate).
    subtotal_charged = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_charged = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_charged = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Shipping destination (set by the owner so a payer can't redirect goods).
    ship_name = models.CharField(max_length=255, blank=True)
    ship_line1 = models.CharField(max_length=255, blank=True)
    ship_line2 = models.CharField(max_length=255, blank=True)
    ship_city = models.CharField(max_length=120, blank=True)
    ship_region = models.CharField(max_length=120, blank=True)
    ship_postal_code = models.CharField(max_length=32, blank=True)
    ship_country = models.CharField(max_length=2, blank=True)
    ship_phone = models.CharField(max_length=32, blank=True)

    coupon_codes = models.JSONField(default=list, blank=True)
    idempotency_key = models.CharField(
        max_length=128, unique=True, null=True, blank=True, default=None
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.number


class OrderLine(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="order_lines")
    # Snapshots so the order is stable even if the catalog changes later.
    sku = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    unit_price_base = models.DecimalField(max_digits=12, decimal_places=2)
    line_total_base = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price_charged = models.DecimalField(max_digits=12, decimal_places=2)
    line_total_charged = models.DecimalField(max_digits=12, decimal_places=2)
    fulfillment_type = models.CharField(max_length=20)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.sku} x{self.quantity}"


class OrderInquiry(BaseModel):
    """A 'chat to order' lead — captured when a shopper taps the order button.

    Persisted so a lead is never lost even if the store's Telegram bot isn't
    configured (in which case the real-time push is skipped, but the inquiry is
    still here for the admin to follow up). ``summary`` is the exact text we sent
    / pre-filled for the chosen channel.
    """

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        WHATSAPP = "whatsapp", "WhatsApp"
        CALL = "call", "Call"

    class Context(models.TextChoices):
        PRODUCT = "product", "Product"
        CART = "cart", "Cart"
        CHECKOUT = "checkout", "Checkout"

    channel = models.CharField(max_length=20, choices=Channel.choices)
    context = models.CharField(max_length=20, choices=Context.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_inquiries",
    )
    customer_name = models.CharField(max_length=255, blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    delivered_to_ops = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "order inquiries"

    def __str__(self) -> str:
        return f"{self.channel} · {self.context} · {self.created_at:%Y-%m-%d}"
