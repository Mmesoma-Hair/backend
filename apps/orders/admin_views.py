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
from .models import Order, OrderInquiry, OrderStatus
from .serializers import OrderSerializer


class TransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)


class MarkShippedSerializer(serializers.Serializer):
    tracking_number = serializers.CharField(required=False, allow_blank=True, default="")
    carrier = serializers.CharField(required=False, allow_blank=True, default="")


class OrderInquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderInquiry
        fields = (
            "id",
            "channel",
            "context",
            "customer_name",
            "customer_phone",
            "note",
            "summary",
            "delivered_to_ops",
            "created_at",
        )


class OrderInquiryAdminViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Read-only 'chat to order' leads for the admin to follow up on."""

    permission_classes = [IsAdminRole]
    queryset = OrderInquiry.objects.all()
    serializer_class = OrderInquirySerializer
    filterset_fields = ["channel", "context"]
    search_fields = ["customer_name", "customer_phone", "summary"]


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

    @extend_schema(
        request=MarkShippedSerializer, responses={200: OrderSerializer}, tags=["orders-admin"]
    )
    @action(detail=True, methods=["post"], url_path="mark-shipped")
    def mark_shipped(self, request: Request, number: str | None = None) -> Response:
        """Mark the order's pending internal shipments as shipped.

        Flips internal shipments PENDING → SHIPPED (with optional tracking /
        carrier), fires the shipped email, and reconciles the order status.
        Dropship shipments are supplier-driven and untouched here.
        """
        from apps.fulfillment import services as fulfillment_services

        order = self.get_object()
        serializer = MarkShippedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = order.status
        shipped = fulfillment_services.mark_internal_shipped(
            order,
            tracking_number=serializer.validated_data["tracking_number"],
            carrier=serializer.validated_data["carrier"],
        )
        order.refresh_from_db()
        record_audit(
            actor=request.user,
            action=AuditLog.Action.UPDATE,
            target_type="orders.Order",
            target_id=order.number,
            changes={"status": {"before": before, "after": order.status}},
            metadata={
                "mark_shipped": True,
                "shipments": len(shipped),
                "tracking_number": serializer.validated_data["tracking_number"],
                "carrier": serializer.validated_data["carrier"],
            },
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
