"""Admin order management (role: admin). Status overrides + refund.

Expanded with full audit logging in Phase 8.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.common.audit import record_audit
from apps.common.models import AuditLog

from . import services
from .models import Order, OrderStatus
from .serializers import OrderSerializer


class TransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)


class OrderAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminRole]
    queryset = Order.objects.all().prefetch_related("lines")
    serializer_class = OrderSerializer
    lookup_field = "number"
    filterset_fields = ["status", "currency"]
    search_fields = ["number", "contact_email", "payer_email"]

    @extend_schema(
        request=TransitionSerializer, responses={200: OrderSerializer}, tags=["orders-admin"]
    )
    @action(detail=True, methods=["post"])
    def transition(self, request: Request, number: str | None = None) -> Response:
        order = self.get_object()
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = order.status
        target = serializer.validated_data["status"]
        services.transition(order, target)
        record_audit(
            actor=request.user,
            action=AuditLog.Action.UPDATE,
            target_type="orders.Order",
            target_id=order.number,
            changes={"status": {"before": before, "after": target}},
        )
        return Response(OrderSerializer(order).data)

    @extend_schema(responses={200: OrderSerializer}, tags=["orders-admin"])
    @action(detail=True, methods=["post"])
    def refund(self, request: Request, number: str | None = None) -> Response:
        order = self.get_object()
        before = order.status
        services.transition(order, OrderStatus.REFUNDED)
        record_audit(
            actor=request.user,
            action=AuditLog.Action.UPDATE,
            target_type="orders.Order",
            target_id=order.number,
            changes={"status": {"before": before, "after": OrderStatus.REFUNDED}},
            metadata={"refund": True},
        )
        return Response(OrderSerializer(order).data)
