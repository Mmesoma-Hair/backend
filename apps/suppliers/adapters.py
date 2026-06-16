"""Pluggable supplier integrations.

Every supplier integration implements the same ``SupplierAdapter`` methods so the
rest of the system never branches on which supplier it's talking to. A concrete
``MockSupplierAdapter`` ships for tests/dev (no network).
"""

from __future__ import annotations

import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import Supplier


@dataclass
class PlacedOrder:
    external_ref: str
    status: str  # placed | processing | shipped | cancelled


@dataclass
class OrderStatus:
    status: str
    tracking_number: str = ""
    carrier: str = ""


class SupplierAdapter(ABC):
    key = "base"

    def __init__(self, supplier: Supplier) -> None:
        self.supplier = supplier

    @abstractmethod
    def fetch_inventory(self) -> dict[str, int]:
        """Return supplier-reported availability keyed by SKU."""

    @abstractmethod
    def fetch_prices(self) -> dict[str, Decimal]:
        """Return supplier wholesale prices keyed by SKU (base currency)."""

    @abstractmethod
    def place_order(self, lines: list[dict[str, Any]]) -> PlacedOrder:
        """Forward order lines to the supplier; return an external reference."""

    @abstractmethod
    def fetch_order_status(self, external_ref: str) -> OrderStatus:
        """Poll the status of a previously placed supplier order."""


class MockSupplierAdapter(SupplierAdapter):
    """Deterministic, network-free adapter for tests and local dev."""

    key = "mock"

    def fetch_inventory(self) -> dict[str, int]:
        return {}

    def fetch_prices(self) -> dict[str, Decimal]:
        return {}

    def place_order(self, lines: list[dict[str, Any]]) -> PlacedOrder:
        return PlacedOrder(external_ref=f"sup_{secrets.token_hex(6)}", status="processing")

    def fetch_order_status(self, external_ref: str) -> OrderStatus:
        # The mock supplier reports the order as shipped with a tracking number.
        return OrderStatus(
            status="shipped",
            tracking_number=f"TRK{secrets.token_hex(5).upper()}",
            carrier="MockExpress",
        )


_ADAPTERS: dict[str, type[SupplierAdapter]] = {"mock": MockSupplierAdapter}


def get_adapter(supplier: Supplier) -> SupplierAdapter:
    adapter_cls = _ADAPTERS.get(supplier.adapter, MockSupplierAdapter)
    return adapter_cls(supplier)
