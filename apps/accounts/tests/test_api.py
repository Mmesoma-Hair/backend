from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import services
from apps.accounts.models import Role

from .factories import UserFactory


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_full_auth_flow_register_login_refresh_access_protected(client: APIClient) -> None:
    # 1) Register
    reg = client.post(
        reverse("api-v1:register"),
        {"email": "flow@example.com", "password": "Sup3rSecret!", "full_name": "Flow"},
        format="json",
    )
    assert reg.status_code == 201
    assert reg.data["email"] == "flow@example.com"
    assert reg.data["role"] == Role.CUSTOMER

    # 2) Login -> tokens
    login = client.post(
        reverse("api-v1:login"),
        {"email": "flow@example.com", "password": "Sup3rSecret!"},
        format="json",
    )
    assert login.status_code == 200
    access = login.data["access"]
    refresh = login.data["refresh"]
    assert login.data["user"]["email"] == "flow@example.com"

    # 3) Protected route without token -> 401
    assert client.get(reverse("api-v1:me")).status_code == 401

    # 4) Protected route with access token -> 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    me = client.get(reverse("api-v1:me"))
    assert me.status_code == 200
    assert me.data["email"] == "flow@example.com"

    # 5) Refresh -> new access (and rotated refresh)
    client.credentials()  # clear
    refreshed = client.post(reverse("api-v1:token-refresh"), {"refresh": refresh}, format="json")
    assert refreshed.status_code == 200
    assert "access" in refreshed.data


@pytest.mark.django_db
def test_login_rejects_bad_credentials(client: APIClient) -> None:
    UserFactory(email="real@example.com", password="OldPass123!")
    resp = client.post(
        reverse("api-v1:login"),
        {"email": "real@example.com", "password": "nope"},
        format="json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_logout_blacklists_refresh(client: APIClient) -> None:
    user = UserFactory(email="lo@example.com", password="OldPass123!")
    login = client.post(
        reverse("api-v1:login"), {"email": user.email, "password": "OldPass123!"}, format="json"
    )
    access, refresh = login.data["access"], login.data["refresh"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    out = client.post(reverse("api-v1:logout"), {"refresh": refresh}, format="json")
    assert out.status_code == 205
    # The blacklisted refresh can no longer be used.
    client.credentials()
    again = client.post(reverse("api-v1:token-refresh"), {"refresh": refresh}, format="json")
    assert again.status_code == 401


@pytest.mark.django_db
def test_password_reset_request_always_200_and_sends_when_exists(client: APIClient) -> None:
    from apps.notifications.channels.email import MemoryEmailBackend

    UserFactory(email="pr@example.com", password="OldPass123!")
    MemoryEmailBackend.outbox.clear()
    hit = client.post(reverse("api-v1:password-reset"), {"email": "pr@example.com"}, format="json")
    miss = client.post(reverse("api-v1:password-reset"), {"email": "no@example.com"}, format="json")
    assert hit.status_code == 200 and miss.status_code == 200
    # Only the existing account triggered an email (via the notifications layer).
    assert len(MemoryEmailBackend.outbox) == 1


@pytest.mark.django_db
def test_password_reset_confirm(client: APIClient) -> None:
    user = UserFactory(email="prc@example.com", password="OldPass123!")
    uid, token = services.generate_password_reset(email=user.email)  # type: ignore[misc]
    resp = client.post(
        reverse("api-v1:password-reset-confirm"),
        {"uid": uid, "token": token, "new_password": "BrandNew123!"},
        format="json",
    )
    assert resp.status_code == 204
    user.refresh_from_db()
    assert user.check_password("BrandNew123!")


@pytest.mark.django_db
def test_me_patch_updates_profile(client: APIClient) -> None:
    user = UserFactory(password="OldPass123!")
    login = client.post(
        reverse("api-v1:login"), {"email": user.email, "password": "OldPass123!"}, format="json"
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    resp = client.patch(
        reverse("api-v1:me"), {"full_name": "Renamed", "phone": "+1999"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["full_name"] == "Renamed"
    assert resp.data["profile"]["phone"] == "+1999"
