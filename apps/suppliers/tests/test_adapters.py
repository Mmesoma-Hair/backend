"""Real connectors: JSON API + CSV feed parse inventory/prices (mocked HTTP)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.suppliers import adapters
from apps.suppliers.models import Supplier


class FakeResp:
    def __init__(self, *, json_data=None, text="", status=200):
        self._json = json_data
        self.text = text
        self.content = b"x"
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._json


@pytest.mark.django_db
def test_http_json_adapter_dict_and_list_shapes(monkeypatch) -> None:
    supplier = Supplier.objects.create(
        name="API Co",
        code="api",
        adapter="http_json",
        api_base_url="https://supplier.test/api",
        api_key="k",
    )

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/inventory"):
            return FakeResp(json_data={"SKU1": 5, "SKU2": "3"})  # dict shape
        if url.endswith("/prices"):
            return FakeResp(json_data=[{"sku": "SKU1", "cost": "9.99"}])  # list shape
        raise AssertionError(url)

    monkeypatch.setattr(adapters.requests, "get", fake_get)
    a = adapters.get_adapter(supplier)
    assert a.fetch_inventory() == {"SKU1": 5, "SKU2": 3}
    assert a.fetch_prices() == {"SKU1": Decimal("9.99")}


@pytest.mark.django_db
def test_http_json_place_order(monkeypatch) -> None:
    supplier = Supplier.objects.create(
        name="API Co", code="api2", adapter="http_json", api_base_url="https://s.test"
    )

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/orders")
        return FakeResp(json_data={"reference": "SUP-123", "status": "processing"})

    monkeypatch.setattr(adapters.requests, "post", fake_post)
    placed = adapters.get_adapter(supplier).place_order([{"sku": "A", "qty": 1}])
    assert placed.external_ref == "SUP-123"
    assert placed.status == "processing"


@pytest.mark.django_db
def test_csv_feed_adapter(monkeypatch) -> None:
    supplier = Supplier.objects.create(
        name="Feed Co",
        code="feed",
        adapter="csv",
        api_base_url="https://supplier.test/feed.csv",
    )
    csv_text = "SKU,Cost,Available\nMUG-001,4.50,12\nTEE-001,8.00,0\n"
    monkeypatch.setattr(
        adapters.requests, "get", lambda url, headers=None, timeout=None: FakeResp(text=csv_text)
    )
    a = adapters.get_adapter(supplier)
    assert a.fetch_inventory() == {"MUG-001": 12, "TEE-001": 0}
    assert a.fetch_prices() == {"MUG-001": Decimal("4.50"), "TEE-001": Decimal("8.00")}


def test_adapter_registry_has_real_connectors() -> None:
    keys = {a["key"] for a in adapters.ADAPTER_INFO}
    assert {"mock", "http_json", "csv"} <= keys
