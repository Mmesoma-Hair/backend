"""Admin currency management (role: admin). Expanded with audit in Phase 8."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.common.audit_mixins import AuditedModelViewSet

from . import selectors, services
from .models import Currency


class CurrencyAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = (
            "code",
            "name",
            "symbol",
            "decimal_places",
            "rounding_increment",
            "charm_pricing",
            "is_active",
            "position",
        )


class CurrencyAdminViewSet(AuditedModelViewSet):
    permission_classes = [IsAdminRole]
    queryset = Currency.objects.all()
    serializer_class = CurrencyAdminSerializer

    @extend_schema(responses={200: dict}, tags=["currency-admin"])
    @action(detail=False, methods=["post"], url_path="refresh-rates")
    def refresh_rates(self, request: Request) -> Response:
        """Trigger an immediate FX refresh from the configured provider."""
        from apps.common.audit import record_audit
        from apps.common.models import AuditLog

        result = services.refresh_rates()
        record_audit(
            actor=request.user,
            action=AuditLog.Action.OTHER,
            target_type="currency.ExchangeRate",
            target_id="refresh",
            metadata=result,
        )
        return Response(result)

    @extend_schema(responses={200: dict}, tags=["currency-admin"])
    @action(detail=False, methods=["get"], url_path="rates-status")
    def rates_status(self, request: Request) -> Response:
        return Response(selectors.rates_status())
