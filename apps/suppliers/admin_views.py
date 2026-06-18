"""Admin supplier management (role: admin)."""

from __future__ import annotations

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.catalog.models import Variant
from apps.common.audit_mixins import AuditedModelViewSet

from . import services
from .adapters import ADAPTER_INFO
from .models import Supplier


class SupplierAdminSerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

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
            "markup_percent",
            "product_count",
            "updated_at",
        )
        read_only_fields = ("product_count", "updated_at")
        extra_kwargs = {
            "api_key": {"write_only": True},
            "code": {"required": False},
        }

    def validate(self, attrs: dict) -> dict:
        # Auto-generate a code from the name so admins never need to know slugs.
        if not attrs.get("code") and attrs.get("name"):
            from django.utils.text import slugify

            base = slugify(attrs["name"]) or "supplier"
            code, i = base, 2
            while (
                Supplier.objects.filter(code=code)
                .exclude(id=getattr(self.instance, "id", None))
                .exists()
            ):
                code, i = f"{base}-{i}", i + 1
            attrs["code"] = code
        return attrs

    def get_product_count(self, obj: Supplier) -> int:
        return Variant.objects.filter(
            Q(supplier=obj) | Q(supplier__isnull=True, product__supplier=obj)
        ).count()


class SupplierAdminViewSet(AuditedModelViewSet):
    permission_classes = [IsAdminRole]
    queryset = Supplier.objects.all().order_by("name")
    serializer_class = SupplierAdminSerializer
    search_fields = ["name", "code"]

    def perform_update(self, serializer: SupplierAdminSerializer) -> None:
        before = serializer.instance.markup_percent
        supplier = serializer.save()
        # Changing the markup re-prices all of that supplier's dropship products.
        if supplier.markup_percent != before:
            services.recompute_prices(supplier)

    @extend_schema(responses={200: dict}, tags=["suppliers-admin"])
    @action(detail=False, methods=["get"])
    def adapters(self, request: Request) -> Response:
        """Available connection types for the 'Add supplier' dropdown."""
        return Response(ADAPTER_INFO)

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
