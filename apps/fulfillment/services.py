"""The fulfillment routing engine.

On ``order.paid`` each line is routed by its fulfillment type: internal lines
ship from a warehouse (consuming reserved stock); dropship lines are grouped by
supplier and forwarded via the adapter. Shipment statuses reconcile up into the
order status (routing → partially_fulfilled → fulfilled).
"""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction

from apps.catalog.models import FulfillmentType
from apps.inventory import services as inventory_services
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus
from apps.suppliers.adapters import get_adapter
from apps.suppliers.models import Supplier

from .models import Shipment, ShipmentLine, SupplierOrder


def _line_ref(order: Order, order_line_id) -> str:
    return f"order:{order.id}:{order_line_id}"


@transaction.atomic
def route_order(order: Order) -> Order:
    """Route a paid order's lines to internal/dropship fulfillment, then reconcile."""
    if order.status == OrderStatus.PAID:
        order_services.transition(order, OrderStatus.ROUTING)

    lines = list(order.lines.select_related("variant", "variant__product"))
    internal = [ln for ln in lines if ln.fulfillment_type == FulfillmentType.INTERNAL]
    dropship_by_supplier: dict[int, list] = defaultdict(list)
    for ln in lines:
        if ln.fulfillment_type == FulfillmentType.DROPSHIP:
            supplier_id = ln.variant.effective_supplier_id
            if supplier_id is not None:
                dropship_by_supplier[supplier_id].append(ln)

    if internal:
        _ship_internal(order, internal)

    for supplier_id, sup_lines in dropship_by_supplier.items():
        _place_dropship(order, Supplier.objects.get(id=supplier_id), sup_lines)

    reconcile(order)
    return order


def _ship_internal(order: Order, lines: list) -> None:
    """Create the internal shipment **pending** and commit its stock.

    Shipping itself is a deliberate admin action (``mark_internal_shipped``), so
    the shipment starts PENDING and no "shipped" email goes out at payment time.
    Stock, however, is consumed now: reservations expire on a TTL, so a paid
    order must commit its stock immediately or a background task could release it.
    Shipment status is tracked separately from stock.
    """
    warehouse = inventory_services.get_default_warehouse()
    shipment = Shipment.objects.create(
        order=order,
        kind=Shipment.Kind.INTERNAL,
        status=Shipment.Status.PENDING,
        warehouse=warehouse,
    )
    for ln in lines:
        ShipmentLine.objects.create(shipment=shipment, order_line=ln, quantity=ln.quantity)
        # Consume the reserved stock for this line (permanently removes it).
        inventory_services.consume(_line_ref(order, ln.id))


def _place_dropship(order: Order, supplier: Supplier, lines: list) -> None:
    adapter = get_adapter(supplier)
    placed = adapter.place_order(
        [{"sku": ln.sku, "quantity": ln.quantity, "title": ln.title} for ln in lines]
    )
    shipment = Shipment.objects.create(
        order=order,
        kind=Shipment.Kind.DROPSHIP,
        status=Shipment.Status.PENDING,
        supplier=supplier,
    )
    for ln in lines:
        ShipmentLine.objects.create(shipment=shipment, order_line=ln, quantity=ln.quantity)
        # Dropship items aren't owned stock — release the placeholder reservation.
        inventory_services.release(_line_ref(order, ln.id))
    SupplierOrder.objects.create(
        order=order,
        supplier=supplier,
        shipment=shipment,
        external_ref=placed.external_ref,
        status=SupplierOrder.Status.PROCESSING,
    )


@transaction.atomic
def mark_internal_shipped(
    order: Order, *, tracking_number: str = "", carrier: str = ""
) -> list[Shipment]:
    """Admin action: flip the order's pending **internal** shipments to SHIPPED.

    Optionally stamps a tracking number / carrier, fires the (per-shipment,
    idempotent) "shipped" email, and reconciles the order up to fulfilled /
    partially fulfilled. Dropship shipments are left to the supplier poll, so
    they're untouched here. Re-running is a no-op once nothing is pending.
    """
    pending = list(
        order.shipments.filter(
            kind=Shipment.Kind.INTERNAL, status=Shipment.Status.PENDING
        ).prefetch_related("lines")
    )
    if not pending:
        return []

    from apps.notifications.notify import on_shipment_shipped

    for shipment in pending:
        shipment.status = Shipment.Status.SHIPPED
        if tracking_number:
            shipment.tracking_number = tracking_number
        if carrier:
            shipment.carrier = carrier
        shipment.save(update_fields=["status", "tracking_number", "carrier", "updated_at"])
        on_shipment_shipped(order, shipment)

    reconcile(order)
    return pending


@transaction.atomic
def reconcile(order: Order) -> Order:
    """Roll shipment statuses up into the order status."""
    shipped_qty: dict[str, int] = defaultdict(int)
    for shipment in order.shipments.filter(
        status__in=[Shipment.Status.SHIPPED, Shipment.Status.DELIVERED]
    ).prefetch_related("lines"):
        for sl in shipment.lines.all():
            shipped_qty[str(sl.order_line_id)] += sl.quantity

    lines = list(order.lines.all())
    fully = all(shipped_qty.get(str(ln.id), 0) >= ln.quantity for ln in lines)
    any_shipped = any(shipped_qty.get(str(ln.id), 0) > 0 for ln in lines)

    target = None
    if fully:
        target = OrderStatus.FULFILLED
    elif any_shipped:
        target = OrderStatus.PARTIALLY_FULFILLED

    if target and order.status != target:
        from apps.orders.state_machine import can_transition

        if can_transition(order.status, target):
            order_services.transition(order, target)
    return order


@transaction.atomic
def poll_supplier_orders() -> int:
    """Poll open supplier orders; mark shipped ones and reconcile. Returns count updated."""
    updated = 0
    open_orders = SupplierOrder.objects.filter(
        status__in=[SupplierOrder.Status.PLACED, SupplierOrder.Status.PROCESSING]
    ).select_related("supplier", "shipment", "order")
    for sup_order in open_orders:
        result = get_adapter(sup_order.supplier).fetch_order_status(sup_order.external_ref)
        if result.status == "shipped":
            sup_order.status = SupplierOrder.Status.SHIPPED
            sup_order.save(update_fields=["status", "updated_at"])
            if sup_order.shipment_id:
                shipment = sup_order.shipment
                shipment.status = Shipment.Status.SHIPPED
                shipment.tracking_number = result.tracking_number
                shipment.carrier = result.carrier
                shipment.save(update_fields=["status", "tracking_number", "carrier", "updated_at"])
                from apps.notifications.notify import on_shipment_shipped

                on_shipment_shipped(sup_order.order, shipment)
            reconcile(sup_order.order)
            updated += 1
    return updated
