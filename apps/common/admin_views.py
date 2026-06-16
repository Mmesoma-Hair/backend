"""Admin audit-log read API (role: admin)."""

from __future__ import annotations

from rest_framework import mixins, serializers, viewsets

from apps.accounts.permissions import IsAdminRole

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = (
            "id",
            "created_at",
            "actor_label",
            "action",
            "target_type",
            "target_id",
            "changes",
            "metadata",
        )


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminRole]
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    filterset_fields = ["action", "target_type"]
    search_fields = ["target_id", "actor_label"]
