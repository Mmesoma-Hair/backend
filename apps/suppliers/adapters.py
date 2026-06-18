"""Pluggable supplier integrations.

Every supplier integration implements the same ``SupplierAdapter`` methods so the
rest of the system never branches on which supplier it's talking to. A concrete
``MockSupplierAdapter`` ships for tests/dev (no network).
"""

from __future__ import annotations

import csv
import io
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from .models import Supplier

_TIMEOUT = 20


class SupplierError(Exception):
    pass


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


def _normalize(data: Any, value_keys: tuple[str, ...]) -> dict[str, Any]:
    """Accept {sku: value} or [{sku, <value>}] (optionally under a 'data' key)."""
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            data = data["data"]
        else:
            return {str(k): v for k, v in data.items()}
    out: dict[str, Any] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            sku = item.get("sku") or item.get("SKU")
            if not sku:
                continue
            val = next((item[k] for k in value_keys if k in item), None)
            if val is not None:
                out[str(sku)] = val
    return out


class HttpJsonSupplierAdapter(SupplierAdapter):
    """Connect any supplier that exposes a simple JSON API.

    Expects, relative to the supplier's API base URL (Bearer = API key):
      GET  /inventory  -> {"SKU": qty} or [{"sku","available"}]
      GET  /prices     -> {"SKU": cost} or [{"sku","cost"}]
      POST /orders     -> {"reference"|"id", "status"}
      GET  /orders/<ref> -> {"status","tracking_number","carrier"}
    """

    key = "http_json"

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.supplier.api_key:
            headers["Authorization"] = f"Bearer {self.supplier.api_key}"
        return headers

    def _base(self) -> str:
        if not self.supplier.api_base_url:
            raise SupplierError("This supplier has no API base URL configured.")
        return self.supplier.api_base_url.rstrip("/")

    def _get(self, path: str) -> Any:
        try:
            resp = requests.get(f"{self._base()}{path}", headers=self._headers(), timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SupplierError(f"Supplier request failed: {exc}") from exc
        return resp.json() if resp.content else {}

    def fetch_inventory(self) -> dict[str, int]:
        data = _normalize(self._get("/inventory"), ("available", "quantity", "qty", "stock"))
        return {sku: max(int(float(v)), 0) for sku, v in data.items()}

    def fetch_prices(self) -> dict[str, Decimal]:
        data = _normalize(self._get("/prices"), ("cost", "price", "wholesale"))
        return {sku: Decimal(str(v)) for sku, v in data.items()}

    def place_order(self, lines: list[dict[str, Any]]) -> PlacedOrder:
        try:
            resp = requests.post(
                f"{self._base()}/orders",
                json={"lines": lines},
                headers=self._headers(),
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SupplierError(f"Supplier order failed: {exc}") from exc
        data = resp.json() if resp.content else {}
        return PlacedOrder(
            external_ref=str(data.get("reference") or data.get("id") or ""),
            status=data.get("status", "processing"),
        )

    def fetch_order_status(self, external_ref: str) -> OrderStatus:
        data = self._get(f"/orders/{external_ref}")
        return OrderStatus(
            status=data.get("status", "processing"),
            tracking_number=data.get("tracking_number", ""),
            carrier=data.get("carrier", ""),
        )


class CsvFeedSupplierAdapter(SupplierAdapter):
    """Pull stock + cost from a CSV product feed URL.

    The supplier's API base URL points at a CSV with columns ``sku`` plus
    ``cost``/``price`` and ``available``/``stock``. Orders are placed manually
    (catalog feeds have no order API), so fulfilment is tracked by hand.
    """

    key = "csv"

    def _rows(self) -> list[dict[str, str]]:
        if not self.supplier.api_base_url:
            raise SupplierError("This supplier has no CSV feed URL configured.")
        headers = (
            {"Authorization": f"Bearer {self.supplier.api_key}"} if self.supplier.api_key else {}
        )
        try:
            resp = requests.get(self.supplier.api_base_url, headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SupplierError(f"Could not fetch CSV feed: {exc}") from exc
        reader = csv.DictReader(io.StringIO(resp.text))
        return [
            {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader
        ]

    def fetch_inventory(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self._rows():
            sku = row.get("sku")
            if sku:
                out[sku] = max(int(float(row.get("available") or row.get("stock") or 0)), 0)
        return out

    def fetch_prices(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for row in self._rows():
            sku, cost = row.get("sku"), row.get("cost") or row.get("price")
            if sku and cost:
                out[sku] = Decimal(cost)
        return out

    def place_order(self, lines: list[dict[str, Any]]) -> PlacedOrder:
        # CSV feeds are catalog-only — fulfil manually with the supplier.
        return PlacedOrder(external_ref="manual", status="processing")

    def fetch_order_status(self, external_ref: str) -> OrderStatus:
        return OrderStatus(status="processing")


# Registry + UI metadata (the admin "connection type" dropdown reads this).
ADAPTER_INFO: list[dict[str, Any]] = [
    {
        "key": "mock",
        "label": "Test (mock)",
        "description": "For trying things out — no real supplier. Generates fake stock and tracking.",
        "fields": [],
    },
    {
        "key": "http_json",
        "label": "Custom API (JSON)",
        "description": "Connect any supplier with a JSON API for inventory, prices and orders.",
        "fields": ["api_base_url", "api_key"],
    },
    {
        "key": "csv",
        "label": "Product feed (CSV)",
        "description": "Pull stock and cost from a CSV feed URL. Orders are placed by hand.",
        "fields": ["api_base_url"],
    },
]

_ADAPTERS: dict[str, type[SupplierAdapter]] = {
    "mock": MockSupplierAdapter,
    "http_json": HttpJsonSupplierAdapter,
    "csv": CsvFeedSupplierAdapter,
}


def get_adapter(supplier: Supplier) -> SupplierAdapter:
    adapter_cls = _ADAPTERS.get(supplier.adapter, MockSupplierAdapter)
    return adapter_cls(supplier)
