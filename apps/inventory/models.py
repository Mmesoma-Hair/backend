"""Inventory: per-variant stock with reservations.

Stock and reservations are keyed to ``catalog.Variant`` (the sellable unit), not
to products. ``on_hand`` is owned stock; ``reserved`` is the portion held by
active reservations (e.g. an in-progress checkout). Available = on_hand - reserved.

Dropship variants are not stocked here — their availability is supplier-reported
(Phase 7) — so reservations for them succeed without consuming owned stock.
"""

from __future__ import annotations

from django.db import models

from apps.catalog.models import Variant
from apps.common.models import BaseModel, TimeStampedModel


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=40, unique=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-is_default", "name")

    def __str__(self) -> str:
        return self.name


class StockItem(TimeStampedModel):
    variant = models.ForeignKey(Variant, on_delete=models.CASCADE, related_name="stock_items")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stock_items")
    on_hand = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["variant", "warehouse"], name="uniq_stock_per_wh"),
        ]

    def __str__(self) -> str:
        return f"{self.variant.sku}@{self.warehouse.code}: {self.available} avail"

    @property
    def available(self) -> int:
        return max(self.on_hand - self.reserved, 0)


class Reservation(BaseModel):
    """A hold on stock for a variant, tied to a reference (cart/order)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RELEASED = "released", "Released"
        CONSUMED = "consumed", "Consumed"

    variant = models.ForeignKey(Variant, on_delete=models.CASCADE, related_name="reservations")
    warehouse = models.ForeignKey(
        Warehouse, null=True, blank=True, on_delete=models.SET_NULL, related_name="reservations"
    )
    quantity = models.PositiveIntegerField()
    # Opaque grouping key, e.g. "cart:<uuid>" or "order:<uuid>".
    reference = models.CharField(max_length=120, db_index=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.reference} {self.variant.sku} x{self.quantity} ({self.status})"
