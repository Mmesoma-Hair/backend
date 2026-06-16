"""Admin coupon management (role: admin)."""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.permissions import IsAdminRole
from apps.common.audit_mixins import AuditedModelViewSet

from .models import Coupon


class CouponAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = (
            "id",
            "code",
            "description",
            "discount_type",
            "value",
            "is_active",
            "valid_from",
            "valid_until",
            "min_spend",
            "category",
            "first_order_only",
            "stackable",
            "max_uses",
            "used_count",
        )
        read_only_fields = ("used_count",)


class CouponAdminViewSet(AuditedModelViewSet):
    permission_classes = [IsAdminRole]
    queryset = Coupon.objects.all()
    serializer_class = CouponAdminSerializer
    filterset_fields = ["is_active", "discount_type"]
    search_fields = ["code", "description"]
