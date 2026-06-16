"""User, roles, and profile.

Login is by email (no username). Authorization is driven by an explicit ``role``
field (customer / admin / supplier) rather than overloading ``is_staff`` — staff
flags remain purely for Django-admin access, while DRF permission classes key off
``role``.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimeStampedModel, UUIDModel


class Role(models.TextChoices):
    CUSTOMER = "customer", _("Customer")
    ADMIN = "admin", _("Admin")
    SUPPLIER = "supplier", _("Supplier")


class UserManager(BaseUserManager["User"]):
    """Manager for the email-login custom user."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra: Any) -> User:
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("role", Role.CUSTOMER)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("role", Role.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra["is_staff"] is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra["is_superuser"] is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, UUIDModel, TimeStampedModel):
    email = models.EmailField(_("email address"), unique=True, db_index=True)
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.CUSTOMER, db_index=True
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Grants Django-admin access only.")

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.email

    # Role helpers used by permission classes / services.
    @property
    def is_admin_role(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_supplier(self) -> bool:
        return self.role == Role.SUPPLIER

    @property
    def is_customer(self) -> bool:
        return self.role == Role.CUSTOMER


class Profile(TimeStampedModel):
    """Extended, non-auth profile data. One per user, auto-created via signal."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=32, blank=True)
    marketing_opt_in = models.BooleanField(default=False)
    # Shopper's preferred display currency (resolved against currency module in Phase 4).
    preferred_currency = models.CharField(max_length=3, blank=True)

    # --- Email verification ---
    email_verified = models.BooleanField(default=False)

    # --- Notification preferences (channels the user opts into) ---
    notify_email = models.BooleanField(default=True)
    notify_telegram = models.BooleanField(default=False)
    # The user supplies their own Telegram bot. The token is a secret: never
    # returned by the API (write-only) — only used server-side to deliver.
    telegram_chat_id = models.CharField(max_length=64, blank=True)
    telegram_bot_token = models.CharField(max_length=128, blank=True)

    def __str__(self) -> str:
        return f"Profile<{self.user.email}>"

    @property
    def telegram_connected(self) -> bool:
        return bool(self.telegram_chat_id and self.telegram_bot_token)
