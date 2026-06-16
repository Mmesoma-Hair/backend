"""Admin user/role management (role: admin).

Admins can list users and change role / active status. Role changes are
sensitive, so each is audit-logged. Passwords are never managed here.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.common.audit import diff, record_audit
from apps.common.models import AuditLog

from .models import Role, User


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role", "is_active", "is_staff", "created_at")
        read_only_fields = ("id", "email", "is_staff", "created_at")


class UserAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAdminRole]
    queryset = User.objects.all()
    serializer_class = AdminUserSerializer
    filterset_fields = ["role", "is_active"]
    search_fields = ["email", "full_name"]

    def perform_update(self, serializer: AdminUserSerializer) -> None:
        before = {"role": serializer.instance.role, "is_active": serializer.instance.is_active}
        user = serializer.save()
        after = {"role": user.role, "is_active": user.is_active}
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.UPDATE,
            target_type="accounts.User",
            target_id=str(user.id),
            changes=diff(before, after),
            metadata={"email": user.email},
        )


class RoleChoicesView(viewsets.ViewSet):
    """Expose the available roles for the admin UI."""

    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: dict}, tags=["accounts-admin"])
    def list(self, request: Request) -> Response:
        return Response({"roles": [{"value": v, "label": label} for v, label in Role.choices]})
