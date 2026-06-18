from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import FulfillmentType, Product, Variant
from apps.suppliers import services
from apps.suppliers.adapters import MockSupplierAdapter, SupplierAdapter, get_adapter
from apps.suppliers.models import Supplier, SupplierStock


@pytest.mark.django_db
def test_get_adapter_returns_mock() -> None:
    supplier = Supplier.objects.create(name="Acme", code="acme", adapter="mock")
    adapter = get_adapter(supplier)
    assert isinstance(adapter, MockSupplierAdapter)
    assert isinstance(adapter, SupplierAdapter)


@pytest.mark.django_db
def test_mock_adapter_place_and_status() -> None:
    supplier = Supplier.objects.create(name="Acme", code="acme", adapter="mock")
    adapter = get_adapter(supplier)
    placed = adapter.place_order([{"sku": "X", "quantity": 1}])
    assert placed.external_ref
    status = adapter.fetch_order_status(placed.external_ref)
    assert status.status == "shipped"
    assert status.tracking_number


@pytest.mark.django_db
def test_sync_inventory_and_prices_with_custom_adapter(monkeypatch) -> None:
    supplier = Supplier.objects.create(name="Acme", code="acme", adapter="mock")
    product = Product.objects.create(
        title="D", fulfillment_type=FulfillmentType.DROPSHIP, supplier=supplier
    )
    variant = Variant.objects.create(
        product=product, sku="SKU1", price=Decimal("10.00"), is_default=True, supplier=supplier
    )

    # Patch the mock adapter to return data, exercising the sync plumbing.
    monkeypatch.setattr(MockSupplierAdapter, "fetch_inventory", lambda self: {"SKU1": 42})
    monkeypatch.setattr(MockSupplierAdapter, "fetch_prices", lambda self: {"SKU1": Decimal("8.50")})

    assert services.sync_inventory(supplier) == 1
    assert SupplierStock.objects.get(supplier=supplier, sku="SKU1").available == 42

    assert services.sync_prices(supplier) == 1
    variant.refresh_from_db()
    # Supplier cost is stored; the selling price is cost + the default 50% markup.
    assert variant.cost_price == Decimal("8.50")
    assert variant.price == Decimal("12.75")
