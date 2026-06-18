"""Supplier records + integration config.

Each supplier names a pluggable adapter (see :mod:`apps.suppliers.adapters`) and
carries the connection settings an adapter needs. Dropship variants point at a
supplier; the fulfillment routing engine forwards their order lines via the
adapter.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedModel


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=40, unique=True)
    is_active = models.BooleanField(default=True)

    # Integration config (consumed by the adapter).
    adapter = models.CharField(max_length=40, default="mock", help_text="Adapter key, e.g. 'mock'.")
    api_base_url = models.URLField(blank=True)
    api_key = models.CharField(max_length=255, blank=True)
    sync_cadence_minutes = models.PositiveIntegerField(default=60)
    # Profit margin added on top of the supplier's cost when syncing prices.
    # e.g. 50 → a 10.00 cost item is sold for 15.00.
    markup_percent = models.DecimalField(max_digits=6, decimal_places=2, default=50)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class SupplierStock(TimeStampedModel):
    """Supplier-reported availability for a SKU (dropship items aren't owned stock)."""

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="stock")
    sku = models.CharField(max_length=64, db_index=True)
    available = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["supplier", "sku"], name="uniq_supplier_stock"),
        ]

    def __str__(self) -> str:
        return f"{self.supplier.code}:{self.sku}={self.available}"
