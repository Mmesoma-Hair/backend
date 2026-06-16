from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts import services
from apps.accounts.services import InvalidVerificationToken
from apps.accounts.tests.factories import UserFactory
from apps.notifications.channels.email import MemoryEmailBackend


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_verify_email_roundtrip() -> None:
    user = UserFactory(email="verify@example.com", password="x")
    assert user.profile.email_verified is False
    token = services.generate_email_verification_token(user)
    services.confirm_email_verification(token)
    user.profile.refresh_from_db()
    assert user.profile.email_verified is True


@pytest.mark.django_db
def test_bad_token_rejected() -> None:
    with pytest.raises(InvalidVerificationToken):
        services.confirm_email_verification("not-a-valid-token")


@pytest.mark.django_db
def test_register_sends_verification_email(client: APIClient) -> None:
    MemoryEmailBackend.outbox.clear()
    resp = client.post(
        "/api/v1/auth/register/",
        {"email": "ver@example.com", "password": "Sup3rSecret!"},
        format="json",
    )
    assert resp.status_code == 201
    assert any(
        m.to == "ver@example.com" and "Verify" in m.subject for m in MemoryEmailBackend.outbox
    )


@pytest.mark.django_db
def test_verify_email_endpoint(client: APIClient) -> None:
    user = UserFactory(email="ep@example.com", password="x")
    token = services.generate_email_verification_token(user)
    resp = client.post("/api/v1/auth/verify-email/confirm/", {"token": token}, format="json")
    assert resp.status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.email_verified is True


@pytest.mark.django_db
def test_profile_never_returns_bot_token(client: APIClient) -> None:
    user = UserFactory(email="tok@example.com", password="Pass12345!")
    login = client.post(
        "/api/v1/auth/login/", {"email": user.email, "password": "Pass12345!"}, format="json"
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    # Set a bot token via profile update.
    client.patch(
        "/api/v1/auth/me/",
        {"telegram_bot_token": "123:secret", "telegram_chat_id": "999", "notify_telegram": True},
        format="json",
    )
    me = client.get("/api/v1/auth/me/")
    assert "telegram_bot_token" not in str(me.data)  # secret never exposed
    assert me.data["profile"]["telegram_connected"] is True
    assert me.data["profile"]["notify_telegram"] is True
