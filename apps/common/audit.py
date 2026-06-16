"""Helpers for writing :class:`~apps.common.models.AuditLog` entries.

Services call :func:`record_audit` after a successful mutation. Keeping this in
one place ensures every audit entry is shaped consistently (actor snapshot,
before/after diff) regardless of which domain wrote it.
"""

from __future__ import annotations

from typing import Any

from .models import AuditLog


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a ``{field: {'before': x, 'after': y}}`` map of changed keys."""
    changes: dict[str, dict[str, Any]] = {}
    for key in set(before) | set(after):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes[key] = {"before": old, "after": new}
    return changes


def record_audit(
    *,
    actor: Any = None,
    action: str = AuditLog.Action.OTHER,
    target_type: str,
    target_id: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    actor_label = ""
    if actor is not None and getattr(actor, "is_authenticated", False):
        actor_label = getattr(actor, "email", "") or str(actor)
    else:
        actor = None

    return AuditLog.objects.create(
        actor=actor,
        actor_label=actor_label,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        changes=changes or {},
        metadata=metadata or {},
    )
