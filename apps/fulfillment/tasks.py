"""Async fulfillment tasks."""

from __future__ import annotations

from celery import shared_task

from . import services


@shared_task
def route_order_task(order_id: str) -> str:
    """Route a paid order (called from orders.mark_paid via the _on_paid hook)."""
    from apps.orders.models import Order

    order = Order.objects.filter(id=order_id).first()
    if order is None:
        return "missing"
    services.route_order(order)
    return order.status


@shared_task
def poll_supplier_orders() -> int:
    """Poll open dropship supplier orders and reconcile (Celery Beat)."""
    return services.poll_supplier_orders()
