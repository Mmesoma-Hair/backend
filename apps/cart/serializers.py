from __future__ import annotations

from rest_framework import serializers


class AddItemSerializer(serializers.Serializer):
    variant = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class UpdateItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)


class ApplyCouponSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)


class CreateShareSerializer(serializers.Serializer):
    expires_in_hours = serializers.IntegerField(required=False, allow_null=True, min_value=1)
