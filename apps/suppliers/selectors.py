from __future__ import annotations

from .models import Supplier, SupplierStock


def active_suppliers():
    return Supplier.objects.filter(is_active=True)


def supplier_availability(supplier_id: int, sku: str) -> int | None:
    row = SupplierStock.objects.filter(supplier_id=supplier_id, sku=sku).first()
    return row.available if row else None
