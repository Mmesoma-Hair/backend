"""Admin inventory management (role: admin)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole
from apps.catalog.models import Variant
from apps.common.audit import record_audit
from apps.common.audit_mixins import AuditedModelViewSet
from apps.common.models import AuditLog

from . import services
from .models import StockItem, Warehouse


class WarehouseAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ("id", "name", "code", "is_default", "is_active")


class WarehouseAdminViewSet(AuditedModelViewSet):
    permission_classes = [IsAdminRole]
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseAdminSerializer


class StockItemSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = StockItem
        fields = (
            "id",
            "variant",
            "sku",
            "warehouse",
            "warehouse_code",
            "on_hand",
            "reserved",
            "available",
        )


class SetStockSerializer(serializers.Serializer):
    variant = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=0)
    warehouse_code = serializers.CharField(required=False, allow_blank=True)


class StockAdminView(APIView):
    """List stock items, or set a variant's on-hand quantity."""

    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: StockItemSerializer(many=True)}, tags=["inventory-admin"])
    def get(self, request: Request) -> Response:
        qs = StockItem.objects.select_related("variant", "warehouse")
        variant_id = request.query_params.get("variant")
        if variant_id:
            qs = qs.filter(variant_id=variant_id)
        return Response(StockItemSerializer(qs, many=True).data)

    @extend_schema(
        request=SetStockSerializer, responses={200: StockItemSerializer}, tags=["inventory-admin"]
    )
    def post(self, request: Request) -> Response:
        serializer = SetStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        variant = Variant.objects.filter(id=data["variant"]).first()
        if variant is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        warehouse = None
        if data.get("warehouse_code"):
            warehouse = Warehouse.objects.filter(code=data["warehouse_code"]).first()
        item = services.set_stock(variant, data["quantity"], warehouse=warehouse)
        record_audit(
            actor=request.user,
            action=AuditLog.Action.UPDATE,
            target_type="inventory.StockItem",
            target_id=str(item.id),
            changes={"on_hand": {"after": data["quantity"]}},
            metadata={"sku": variant.sku},
        )
        return Response(StockItemSerializer(item).data)
