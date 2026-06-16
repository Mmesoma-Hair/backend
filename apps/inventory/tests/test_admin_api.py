from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.catalog.models import Product, Variant
from apps.common.models import AuditLog
from apps.inventory.services import available_quantity


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _variant() -> Variant:
    p = Product.objects.create(title="P")
    return Variant.objects.create(product=p, sku="SET-1", price=Decimal("5"), is_default=True)


@pytest.mark.django_db
def test_stock_admin_requires_admin(client: APIClient) -> None:
    assert client.get("/api/v1/admin/inventory/stock/").status_code in (401, 403)
    client.force_authenticate(UserFactory(role=Role.CUSTOMER, password="x"))
    assert client.get("/api/v1/admin/inventory/stock/").status_code == 403


@pytest.mark.django_db
def test_admin_sets_stock_and_audits(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    client.force_authenticate(admin)
    v = _variant()
    resp = client.post(
        "/api/v1/admin/inventory/stock/", {"variant": str(v.id), "quantity": 42}, format="json"
    )
    assert resp.status_code == 200
    assert available_quantity(v) == 42
    assert AuditLog.objects.filter(target_type="inventory.StockItem").exists()
