from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.accounts import services
from apps.accounts.models import Profile, Role, User
from apps.accounts.services import IncorrectPassword, InvalidResetToken
from apps.common.exceptions import DomainError

from .factories import UserFactory


@pytest.mark.django_db
def test_register_creates_user_and_profile() -> None:
    user = services.register_user(
        email="New@Example.com", password="Sup3rSecret!", full_name="New U"
    )
    assert user.email == "New@example.com"  # local part case kept, domain lowered
    assert user.role == Role.CUSTOMER
    assert user.check_password("Sup3rSecret!")
    assert Profile.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_register_self_service_cannot_grant_elevated_role() -> None:
    user = services.register_user(email="x@example.com", password="Sup3rSecret!", role=Role.ADMIN)
    assert user.role == Role.CUSTOMER


@pytest.mark.django_db
def test_register_duplicate_email_rejected() -> None:
    services.register_user(email="dup@example.com", password="Sup3rSecret!")
    with pytest.raises(DomainError):
        services.register_user(email="dup@example.com", password="Sup3rSecret!")


@pytest.mark.django_db
def test_register_weak_password_rejected() -> None:
    with pytest.raises(ValidationError):
        services.register_user(email="weak@example.com", password="123")


@pytest.mark.django_db
def test_change_password_requires_correct_current() -> None:
    user = UserFactory(password="OldPass123!")
    with pytest.raises(IncorrectPassword):
        services.change_password(user=user, current_password="wrong", new_password="NewPass123!")
    services.change_password(user=user, current_password="OldPass123!", new_password="NewPass123!")
    user.refresh_from_db()
    assert user.check_password("NewPass123!")


@pytest.mark.django_db
def test_password_reset_roundtrip() -> None:
    user = UserFactory(email="reset@example.com", password="OldPass123!")
    result = services.generate_password_reset(email="reset@example.com")
    assert result is not None
    uid, token = result
    services.reset_password(uid=uid, token=token, new_password="BrandNew123!")
    user.refresh_from_db()
    assert user.check_password("BrandNew123!")


@pytest.mark.django_db
def test_password_reset_unknown_email_returns_none() -> None:
    assert services.generate_password_reset(email="nobody@example.com") is None


@pytest.mark.django_db
def test_password_reset_bad_token_rejected() -> None:
    user = UserFactory(password="OldPass123!")
    result = services.generate_password_reset(email=user.email)
    assert result is not None
    uid, _token = result
    with pytest.raises(InvalidResetToken):
        services.reset_password(uid=uid, token="not-a-valid-token", new_password="BrandNew123!")


@pytest.mark.django_db
def test_create_superuser_is_admin_role() -> None:
    admin = User.objects.create_superuser(email="root@example.com", password="Sup3rSecret!")
    assert admin.is_admin_role and admin.is_staff and admin.is_superuser


@pytest.mark.django_db
def test_update_profile() -> None:
    user = UserFactory()
    services.update_profile(user=user, full_name="Changed", phone="+15551234567")
    user.refresh_from_db()
    assert user.full_name == "Changed"
    assert user.profile.phone == "+15551234567"
