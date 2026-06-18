"""Dropshipping margin engine: sync stores cost and sells at cost + markup."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import FulfillmentType, Product, Variant
from apps.suppliers import services
from apps.suppliers.models import Supplier


@pytest.fixture
def supplier(db) -> Supplier:
    return Supplier.objects.create(name="Acme", code="acme", adapter="mock", markup_percent=50)


def _dropship_variant(supplier: Supplier, sku: str) -> Variant:
    product = Product.objects.create(
        title=f"P-{sku}", fulfillment_type=FulfillmentType.DROPSHIP, supplier=supplier
    )
    return Variant.objects.create(product=product, sku=sku, price=0, cost_price=0)


def test_sell_price_applies_markup() -> None:
    assert services.sell_price(Decimal("10.00"), Decimal("50")) == Decimal("15.00")
    assert services.sell_price(Decimal("9.99"), Decimal("30")) == Decimal("12.99")
    assert services.sell_price(Decimal("0"), Decimal("50")) == Decimal("0.00")


@pytest.mark.django_db
def test_sync_prices_stores_cost_and_marks_up(supplier, monkeypatch) -> None:
    v = _dropship_variant(supplier, "MUG-001")
    # Mock adapter returns the supplier COST.
    from apps.suppliers.adapters import MockSupplierAdapter

    monkeypatch.setattr(
        MockSupplierAdapter, "fetch_prices", lambda self: {"MUG-001": Decimal("10.00")}
    )
    updated = services.sync_prices(supplier)
    v.refresh_from_db()
    assert updated == 1
    assert v.cost_price == Decimal("10.00")  # what we pay
    assert v.price == Decimal("15.00")  # what the shopper pays (cost + 50%)


@pytest.mark.django_db
def test_changing_markup_reprices_all(supplier) -> None:
    v = _dropship_variant(supplier, "MUG-001")
    v.cost_price = Decimal("20.00")
    v.price = Decimal("30.00")  # was 50%
    v.save()
    supplier.markup_percent = Decimal("100")  # now double
    supplier.save()
    services.recompute_prices(supplier)
    v.refresh_from_db()
    assert v.price == Decimal("40.00")  # 20 + 100%


@pytest.mark.django_db
def test_sync_targets_inherited_supplier(supplier, monkeypatch) -> None:
    # Variant with no direct supplier but its product points at the supplier.
    product = Product.objects.create(
        title="Inherited", fulfillment_type=FulfillmentType.DROPSHIP, supplier=supplier
    )
    v = Variant.objects.create(product=product, sku="INH-1", price=0, cost_price=0, supplier=None)
    from apps.suppliers.adapters import MockSupplierAdapter

    monkeypatch.setattr(
        MockSupplierAdapter, "fetch_prices", lambda self: {"INH-1": Decimal("8.00")}
    )
    services.sync_prices(supplier)
    v.refresh_from_db()
    assert v.cost_price == Decimal("8.00")
    assert v.price == Decimal("12.00")  # 8 + 50%
