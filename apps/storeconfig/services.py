"""Write access to settings — all business rules live here.

Setting a value validates it against the spec, persists it, writes an audit
entry, and busts the read cache. Views never write the model directly.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.common.audit import record_audit
from apps.common.models import AuditLog

from . import selectors
from .models import Setting
from .schema import get_spec


@transaction.atomic
def set_setting(key: str, value: Any, *, actor: Any = None) -> Setting:
    """Validate and persist a single setting, recording an audit entry."""
    spec = get_spec(key)
    coerced = spec.validate(value)  # raises ValidationError on bad input

    before = selectors.get_setting(key)
    setting, created = Setting.objects.update_or_create(
        key=key,
        defaults={"section": spec.section, "value": coerced},
    )
    selectors.invalidate_cache()

    record_audit(
        actor=actor,
        action=AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
        target_type="storeconfig.Setting",
        target_id=key,
        changes={key: {"before": before, "after": coerced}},
    )
    return setting


@transaction.atomic
def set_many(values: dict[str, Any], *, actor: Any = None) -> list[Setting]:
    """Validate-then-write a batch atomically (all valid or nothing persists)."""
    # Validate everything first so a single bad key rejects the whole batch.
    coerced = {key: get_spec(key).validate(val) for key, val in values.items()}
    return [set_setting(key, val, actor=actor) for key, val in coerced.items()]


@transaction.atomic
def reset_setting(key: str, *, actor: Any = None) -> None:
    """Remove an override so the key falls back to its spec default."""
    spec = get_spec(key)
    before = selectors.get_setting(key)
    deleted, _ = Setting.objects.filter(key=key).delete()
    if deleted:
        selectors.invalidate_cache()
        record_audit(
            actor=actor,
            action=AuditLog.Action.DELETE,
            target_type="storeconfig.Setting",
            target_id=key,
            changes={key: {"before": before, "after": spec.default}},
        )
