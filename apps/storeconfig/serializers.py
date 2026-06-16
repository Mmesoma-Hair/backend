from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .schema import SETTINGS


class SettingSpecSerializer(serializers.Serializer):
    """Describes a single configurable key (for admin UIs)."""

    key = serializers.CharField()
    section = serializers.CharField()
    type = serializers.CharField()
    description = serializers.CharField()
    default = serializers.JSONField()
    value = serializers.JSONField()


class SettingWriteSerializer(serializers.Serializer):
    """Carries a single setting value; spec validation happens in the service."""

    value = serializers.JSONField()


class BulkSettingsWriteSerializer(serializers.Serializer):
    values = serializers.DictField(child=serializers.JSONField())

    def validate_values(self, values: dict[str, Any]) -> dict[str, Any]:
        unknown = set(values) - set(SETTINGS)
        if unknown:
            raise serializers.ValidationError(f"Unknown keys: {sorted(unknown)}")
        return values
