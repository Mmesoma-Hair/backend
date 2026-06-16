from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.common.models import AuditLog


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_user_admin_requires_admin_role(client: APIClient) -> None:
    assert client.get("/api/v1/admin/accounts/users/").status_code in (401, 403)
    client.force_authenticate(UserFactory(role=Role.CUSTOMER, password="x"))
    assert client.get("/api/v1/admin/accounts/users/").status_code == 403


@pytest.mark.django_db
def test_admin_changes_user_role_audited(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    target = UserFactory(role=Role.CUSTOMER, password="x")
    client.force_authenticate(admin)

    resp = client.patch(
        f"/api/v1/admin/accounts/users/{target.id}/", {"role": Role.SUPPLIER}, format="json"
    )
    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.role == Role.SUPPLIER
    assert AuditLog.objects.filter(target_type="accounts.User", target_id=str(target.id)).exists()
