from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_audit_log_endpoint_admin_only(client: APIClient) -> None:
    assert client.get("/api/v1/admin/audit/").status_code in (401, 403)
    client.force_authenticate(UserFactory(role=Role.CUSTOMER, password="x"))
    assert client.get("/api/v1/admin/audit/").status_code == 403


@pytest.mark.django_db
def test_coupon_create_is_audited_via_mixin(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    client.force_authenticate(admin)
    resp = client.post(
        "/api/v1/admin/promotions/coupons/",
        {"code": "AUDITME", "discount_type": "percentage", "value": "10"},
        format="json",
    )
    assert resp.status_code == 201
    # The AuditedModelViewSet mixin recorded the create; visible via the audit API.
    audit = client.get("/api/v1/admin/audit/?target_type=promotions.Coupon")
    assert audit.status_code == 200
    results = audit.data["results"] if isinstance(audit.data, dict) else audit.data
    assert any(e["action"] == "create" for e in results)
