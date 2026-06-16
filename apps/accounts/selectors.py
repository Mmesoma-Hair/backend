from __future__ import annotations

from .models import User


def get_user_by_email(email: str) -> User | None:
    return User.objects.filter(email__iexact=email.strip()).first()


def email_exists(email: str) -> bool:
    return User.objects.filter(email__iexact=email.strip()).exists()
