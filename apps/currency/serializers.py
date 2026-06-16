from __future__ import annotations

from rest_framework import serializers

from .models import Currency


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ("code", "name", "symbol", "decimal_places", "is_active", "position")


class MoneySerializer(serializers.Serializer):
    """Display-ready price: base + converted amount, formatting, and rate used."""

    base_amount = serializers.CharField()
    base_currency = serializers.CharField()
    currency = serializers.CharField()
    amount = serializers.CharField()
    formatted = serializers.CharField()
    rate = serializers.CharField()
    converted = serializers.BooleanField()
