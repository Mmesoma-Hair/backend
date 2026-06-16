from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.common.models import AuditLog
from apps.storeconfig import selectors


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_admin_settings_requires_admin_role(client: APIClient) -> None:
    # Anonymous → 401/403.
    assert client.get("/api/v1/admin/storeconfig/settings/").status_code in (401, 403)
    # Customer → 403.
    client.force_authenticate(UserFactory(role=Role.CUSTOMER, password="x"))
    assert client.get("/api/v1/admin/storeconfig/settings/").status_code == 403


@pytest.mark.django_db
def test_admin_changes_setting_takes_effect_and_is_audited(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    client.force_authenticate(admin)

    resp = client.put(
        "/api/v1/admin/storeconfig/settings/store.name/",
        {"value": "Renamed Store"},
        format="json",
    )
    assert resp.status_code == 200
    # The change is effective immediately via the selector (storefront reads this).
    assert selectors.get_setting("store.name") == "Renamed Store"
    # And an audit entry was recorded (CREATE on first override, else UPDATE).
    assert AuditLog.objects.filter(
        target_type="storeconfig.Setting", target_id="store.name"
    ).exists()


@pytest.mark.django_db
def test_setting_change_visible_on_public_config(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    client.force_authenticate(admin)
    client.put(
        "/api/v1/admin/storeconfig/settings/store.name/",
        {"value": "Public Visible"},
        format="json",
    )
    # The public storefront config endpoint reflects it (no auth).
    public = APIClient().get("/api/v1/config/")
    assert public.data["settings"]["store.name"] == "Public Visible"


@pytest.mark.django_db
def test_invalid_setting_value_rejected(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    client.force_authenticate(admin)
    resp = client.put(
        "/api/v1/admin/storeconfig/settings/currency.base/",
        {"value": "DOLLARS"},
        format="json",
    )
    assert resp.status_code == 400
