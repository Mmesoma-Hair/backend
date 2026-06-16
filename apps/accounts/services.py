"""Account business logic: registration, password reset, profile updates.

All rules live here; views only validate request shape and delegate. Password
strength is enforced via Django's configured validators, and password-reset uses
Django's signed token generator (no custom crypto).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.common.exceptions import DomainError

from .models import Profile, Role, User
from .selectors import get_user_by_email

EMAIL_VERIFY_SALT = "accounts.email-verify"
EMAIL_VERIFY_MAX_AGE = 60 * 60 * 24 * 3  # 3 days


class InvalidResetToken(DomainError):
    default_detail = "The password reset link is invalid or has expired."
    default_code = "invalid_reset_token"


class InvalidVerificationToken(DomainError):
    default_detail = "The verification link is invalid or has expired."
    default_code = "invalid_verification_token"


class IncorrectPassword(DomainError):
    default_detail = "The current password is incorrect."
    default_code = "incorrect_password"


@transaction.atomic
def register_user(
    *,
    email: str,
    password: str,
    full_name: str = "",
    role: str = Role.CUSTOMER,
    marketing_opt_in: bool = False,
) -> User:
    """Create a user (+ profile via signal). Self-service registration is always
    a ``customer``; elevated roles are assigned by admins, never by the caller."""
    email = User.objects.normalize_email(email.strip())
    if get_user_by_email(email):
        raise DomainError("An account with this email already exists.", code="email_taken")

    # Self-registration cannot grant admin/supplier roles.
    safe_role = Role.CUSTOMER if role not in {Role.CUSTOMER} else role

    user = User(email=email, full_name=full_name.strip(), role=safe_role)
    validate_password(password, user)  # raises DjangoValidationError -> 400
    user.set_password(password)
    user.save()

    if marketing_opt_in:
        Profile.objects.filter(user=user).update(marketing_opt_in=True)
    return user


@transaction.atomic
def change_password(*, user: User, current_password: str, new_password: str) -> None:
    if not user.check_password(current_password):
        raise IncorrectPassword()
    validate_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])


def generate_password_reset(*, email: str) -> tuple[str, str] | None:
    """Return ``(uid, token)`` for the account, or ``None`` if no such account.

    Callers must not leak which emails exist; the API responds 200 regardless.
    The token is consumed by :func:`reset_password`.
    """
    user = get_user_by_email(email)
    if user is None or not user.is_active:
        return None
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return uid, token


@transaction.atomic
def reset_password(*, uid: str, token: str, new_password: str) -> User:
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=pk)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError) as exc:
        raise InvalidResetToken() from exc

    if not default_token_generator.check_token(user, token):
        raise InvalidResetToken()

    validate_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    return user


@transaction.atomic
def update_profile(*, user: User, full_name: str | None = None, **profile_fields: Any) -> User:
    if full_name is not None:
        user.full_name = full_name.strip()
        user.save(update_fields=["full_name", "updated_at"])

    allowed = {
        "phone",
        "marketing_opt_in",
        "preferred_currency",
        "telegram_chat_id",
        "telegram_bot_token",
        "notify_email",
        "notify_telegram",
    }
    updates = {k: v for k, v in profile_fields.items() if k in allowed and v is not None}
    if updates:
        Profile.objects.filter(user=user).update(**updates)
    user.refresh_from_db()
    return user


# --- Email verification (stateless signed token; not tied to login) ---------
def generate_email_verification_token(user: User) -> str:
    """A signed, time-limited token binding the user id to their current email."""
    return signing.dumps({"uid": str(user.pk), "email": user.email}, salt=EMAIL_VERIFY_SALT)


@transaction.atomic
def confirm_email_verification(token: str) -> User:
    try:
        data = signing.loads(token, salt=EMAIL_VERIFY_SALT, max_age=EMAIL_VERIFY_MAX_AGE)
    except signing.SignatureExpired as exc:
        raise InvalidVerificationToken(
            "The verification link has expired.", code="expired"
        ) from exc
    except signing.BadSignature as exc:
        raise InvalidVerificationToken() from exc

    user = User.objects.filter(pk=data.get("uid")).first()
    if user is None or user.email != data.get("email"):
        # Email changed since the link was issued — token no longer applies.
        raise InvalidVerificationToken()

    Profile.objects.filter(user=user).update(email_verified=True)
    user.refresh_from_db()
    return user
