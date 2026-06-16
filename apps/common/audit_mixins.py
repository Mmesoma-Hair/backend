"""Reusable DRF mixin that audit-logs admin writes.

Mixing :class:`AuditedModelViewSet` into an admin viewset records a consistent
``AuditLog`` entry (actor, action, before/after diff) for every create/update/
delete, so the whole admin surface is audited without per-view boilerplate.
"""

from __future__ import annotations

import json
from typing import Any

from rest_framework import viewsets
from rest_framework.utils.encoders import JSONEncoder

from .audit import diff, record_audit
from .models import AuditLog


def _json_safe(data: Any) -> Any:
    """Coerce serializer output (Decimal/UUID/datetime) into JSON-safe values."""
    return json.loads(json.dumps(data, cls=JSONEncoder))


class AuditedModelViewSet(viewsets.ModelViewSet):
    #: Override to set the audited resource label; defaults to "app.Model".
    audit_target_type: str | None = None

    def _target_type(self) -> str:
        if self.audit_target_type:
            return self.audit_target_type
        model = self.get_queryset().model
        return f"{model._meta.app_label}.{model.__name__}"

    def _snapshot(self, instance: Any) -> dict[str, Any]:
        return _json_safe(self.get_serializer(instance).data)

    def perform_create(self, serializer: Any) -> None:
        instance = serializer.save()
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.CREATE,
            target_type=self._target_type(),
            target_id=instance.pk,
            changes={"after": self._snapshot(instance)},
        )

    def perform_update(self, serializer: Any) -> None:
        before = self._snapshot(serializer.instance)
        instance = serializer.save()
        after = self._snapshot(instance)
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.UPDATE,
            target_type=self._target_type(),
            target_id=instance.pk,
            changes=diff(before, after),
        )

    def perform_destroy(self, instance: Any) -> None:
        before = self._snapshot(instance)
        target_id = instance.pk
        super().perform_destroy(instance)
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.DELETE,
            target_type=self._target_type(),
            target_id=target_id,
            changes={"before": before},
        )
