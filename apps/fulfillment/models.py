"""Fulfillment: shipments, their lines, and dropship supplier orders.

The routing engine creates one shipment per fulfillment path of an order:
internal lines ship from a warehouse; dropship lines are forwarded to a supplier
(tracked by a ``SupplierOrder``). Reconciliation rolls shipment statuses up into
the order's status.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel
from apps.orders.models import Order, OrderLine


class Shipment(BaseModel):
    class Kind(models.TextChoices):
        INTERNAL = "internal", "Internal"
        DROPSHIP = "dropship", "Dropship"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipments")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipments",
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipments",
    )
    tracking_number = models.CharField(max_length=80, blank=True)
    carrier = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"Shipment<{self.order.number}/{self.kind}/{self.status}>"


class ShipmentLine(BaseModel):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(
        OrderLine, on_delete=models.CASCADE, related_name="shipment_lines"
    )
    quantity = models.PositiveIntegerField()

    def __str__(self) -> str:
        return f"{self.order_line.sku} x{self.quantity}"


class SupplierOrder(BaseModel):
    class Status(models.TextChoices):
        PLACED = "placed", "Placed"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="supplier_orders")
    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, related_name="supplier_orders"
    )
    shipment = models.ForeignKey(
        Shipment, null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_orders"
    )
    external_ref = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLACED)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"SupplierOrder<{self.external_ref}/{self.status}>"
