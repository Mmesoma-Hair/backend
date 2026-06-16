"""Async supplier sync tasks (Celery Beat / manual)."""

from __future__ import annotations

from celery import shared_task

from . import services
from .models import Supplier


@shared_task
def sync_supplier(supplier_id: int) -> dict:
    supplier = Supplier.objects.filter(id=supplier_id, is_active=True).first()
    if supplier is None:
        return {"ok": False, "reason": "not_found"}
    return {
        "ok": True,
        "inventory": services.sync_inventory(supplier),
        "prices": services.sync_prices(supplier),
    }


@shared_task
def sync_all_suppliers() -> dict:
    results = {s.code: sync_supplier(s.id) for s in Supplier.objects.filter(is_active=True)}
    return {"synced": len(results), "results": results}
