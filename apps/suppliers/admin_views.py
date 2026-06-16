"""Admin supplier management (role: admin)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.common.audit_mixins import AuditedModelViewSet

from . import services
from .models import Supplier


class SupplierAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = (
            "id",
            "name",
            "code",
            "is_active",
            "adapter",
            "api_base_url",
            "api_key",
            "sync_cadence_minutes",
        )
        extra_kwargs = {"api_key": {"write_only": True}}


class SupplierAdminViewSet(AuditedModelViewSet):
    permission_classes = [IsAdminRole]
    queryset = Supplier.objects.all()
    serializer_class = SupplierAdminSerializer
    search_fields = ["name", "code"]

    @extend_schema(responses={200: dict}, tags=["suppliers-admin"])
    @action(detail=True, methods=["post"])
    def sync(self, request: Request, pk: str | None = None) -> Response:
        supplier = self.get_object()
        return Response(
            {
                "inventory": services.sync_inventory(supplier),
                "prices": services.sync_prices(supplier),
            }
        )
