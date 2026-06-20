"""Inventory business logic: stock levels and reservations.

Reservations are the concurrency-safe primitive used at checkout: reserve holds
stock, release frees it (cancel/expiry), consume removes it permanently (ship).
Row locking (`select_for_update`) prevents overselling under concurrent checkout.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.catalog.models import Variant
from apps.common.exceptions import ConflictError, DomainError

from .models import Reservation, StockItem, Warehouse


class InsufficientStock(ConflictError):
    default_detail = "Not enough stock available."
    default_code = "insufficient_stock"


def get_default_warehouse() -> Warehouse:
    wh = Warehouse.objects.filter(is_default=True, is_active=True).first()
    if wh is None:
        wh, _ = Warehouse.objects.get_or_create(
            code="main", defaults={"name": "Main warehouse", "is_default": True}
        )
    return wh


@transaction.atomic
def set_stock(variant: Variant, quantity: int, *, warehouse: Warehouse | None = None) -> StockItem:
    """Set the on-hand quantity for a variant in a warehouse."""
    if quantity < 0:
        raise DomainError("Quantity cannot be negative.", code="invalid_quantity")
    warehouse = warehouse or get_default_warehouse()
    item, _ = StockItem.objects.get_or_create(variant=variant, warehouse=warehouse)
    item.on_hand = quantity
    # Raise the stock-bar baseline to the new level on restock; selling never
    # lowers it, so the bar depletes from "full" down to out-of-stock.
    item.full_stock = max(item.full_stock, quantity)
    item.save(update_fields=["on_hand", "full_stock", "updated_at"])
    return item


def available_quantity(variant: Variant, *, warehouse: Warehouse | None = None) -> int:
    """Available units for a variant (one warehouse or summed across all)."""
    if variant.is_dropship:
        # Owned stock isn't tracked for dropship; treated as available (supplier
        # availability is reconciled in Phase 7).
        return 10**9
    qs = StockItem.objects.filter(variant=variant)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    agg = qs.aggregate(on_hand=Sum("on_hand"), reserved=Sum("reserved"))
    return max((agg["on_hand"] or 0) - (agg["reserved"] or 0), 0)


@transaction.atomic
def reserve(
    variant: Variant,
    quantity: int,
    *,
    reference: str,
    warehouse: Warehouse | None = None,
    ttl_minutes: int | None = 30,
) -> Reservation:
    """Hold ``quantity`` of a variant for ``reference``.

    For internal variants this locks the stock row and bumps ``reserved``,
    raising :class:`InsufficientStock` if not enough is available. Dropship
    variants reserve without touching owned stock.
    """
    if quantity <= 0:
        raise DomainError("Quantity must be positive.", code="invalid_quantity")

    expires_at = timezone.now() + timedelta(minutes=ttl_minutes) if ttl_minutes else None

    if variant.is_dropship:
        return Reservation.objects.create(
            variant=variant,
            warehouse=None,
            quantity=quantity,
            reference=reference,
            expires_at=expires_at,
        )

    warehouse = warehouse or get_default_warehouse()
    item, _ = StockItem.objects.select_for_update().get_or_create(
        variant=variant, warehouse=warehouse
    )
    if item.available < quantity:
        raise InsufficientStock()
    item.reserved = F("reserved") + quantity
    item.save(update_fields=["reserved", "updated_at"])

    return Reservation.objects.create(
        variant=variant,
        warehouse=warehouse,
        quantity=quantity,
        reference=reference,
        expires_at=expires_at,
    )


@transaction.atomic
def release(reference: str) -> int:
    """Release all active reservations for a reference (cancel/expiry). Returns count."""
    reservations = list(
        Reservation.objects.select_for_update().filter(
            reference=reference, status=Reservation.Status.ACTIVE
        )
    )
    for res in reservations:
        _free(res)
        res.status = Reservation.Status.RELEASED
        res.save(update_fields=["status", "updated_at"])
    return len(reservations)


@transaction.atomic
def consume(reference: str) -> int:
    """Permanently remove reserved stock (e.g. on shipment). Returns count."""
    reservations = list(
        Reservation.objects.select_for_update().filter(
            reference=reference, status=Reservation.Status.ACTIVE
        )
    )
    for res in reservations:
        if res.warehouse_id is not None:
            item = (
                StockItem.objects.select_for_update()
                .filter(variant=res.variant, warehouse=res.warehouse)
                .first()
            )
            if item is not None:
                item.on_hand = F("on_hand") - res.quantity
                item.reserved = F("reserved") - res.quantity
                item.save(update_fields=["on_hand", "reserved", "updated_at"])
        res.status = Reservation.Status.CONSUMED
        res.save(update_fields=["status", "updated_at"])
    return len(reservations)


def _free(reservation: Reservation) -> None:
    """Return a reservation's held units to availability."""
    if reservation.warehouse_id is None:
        return
    item = (
        StockItem.objects.select_for_update()
        .filter(variant=reservation.variant, warehouse=reservation.warehouse)
        .first()
    )
    if item is not None:
        item.reserved = F("reserved") - reservation.quantity
        item.save(update_fields=["reserved", "updated_at"])


@transaction.atomic
def release_expired() -> int:
    """Release reservations whose TTL has elapsed. Called by a periodic task."""
    now = timezone.now()
    expired = Reservation.objects.select_for_update().filter(
        status=Reservation.Status.ACTIVE, expires_at__isnull=False, expires_at__lte=now
    )
    refs = list(expired.values_list("reference", flat=True).distinct())
    count = 0
    for ref in refs:
        count += release(ref)
    return count
