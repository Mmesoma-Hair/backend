from __future__ import annotations

from typing import Any

from rest_framework import serializers
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer as BaseTokenObtainPairSerializer,
)

from .models import Address, Profile, User


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = (
            "id",
            "label",
            "name",
            "line1",
            "line2",
            "city",
            "region",
            "postal_code",
            "country",
            "phone",
            "is_default",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class ProfileSerializer(serializers.ModelSerializer):
    telegram_connected = serializers.BooleanField(read_only=True)

    class Meta:
        model = Profile
        fields = (
            "phone",
            "marketing_opt_in",
            "preferred_currency",
            "email_verified",
            "notify_email",
            "notify_telegram",
            "telegram_chat_id",
            "telegram_connected",
        )
        # The bot token is a secret and is never returned by the API.


class UserSerializer(serializers.ModelSerializer):
    """The authenticated user's own representation (``/auth/me/``)."""

    profile = ProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role", "is_active", "date_joined", "profile")
        read_only_fields = fields

    date_joined = serializers.DateTimeField(source="created_at", read_only=True)


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    marketing_opt_in = serializers.BooleanField(required=False, default=False)


class ProfileUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    marketing_opt_in = serializers.BooleanField(required=False)
    preferred_currency = serializers.CharField(required=False, allow_blank=True, max_length=3)
    notify_email = serializers.BooleanField(required=False)
    notify_telegram = serializers.BooleanField(required=False)
    telegram_chat_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    # Write-only: stored but never echoed back.
    telegram_bot_token = serializers.CharField(
        required=False, allow_blank=True, max_length=128, write_only=True
    )


class EmailVerifyConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )


class TokenObtainPairSerializer(BaseTokenObtainPairSerializer):
    """Adds identity claims and returns the user payload alongside the tokens."""

    @classmethod
    def get_token(cls, user: User) -> Any:  # type: ignore[override]
        token = super().get_token(user)
        token["email"] = user.email
        token["role"] = user.role
        return token

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data
