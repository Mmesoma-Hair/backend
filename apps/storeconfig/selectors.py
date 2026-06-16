"""Read access to settings — the single ``get_setting`` entry point.

The whole settings map is cached as one dict (cheap, rarely changes) and
invalidated on write. Callers never touch the model directly.
"""

from __future__ import annotations

from typing import Any

from django.core.cache import cache

from .models import Setting
from .schema import SETTINGS, get_spec

_CACHE_KEY = "storeconfig:all"
_SENTINEL = object()


def _load_all() -> dict[str, Any]:
    """Return {key: effective_value} for every known spec (defaults + overrides)."""
    overrides = {s.key: s.value for s in Setting.objects.all()}
    resolved: dict[str, Any] = {}
    for key, spec in SETTINGS.items():
        resolved[key] = overrides.get(key, spec.default)
    return resolved


def get_all_settings() -> dict[str, Any]:
    # The cache is an optimisation, not a dependency: if it's unavailable we
    # still serve settings straight from the DB so browsing/checkout never
    # breaks because Redis is down.
    try:
        cached = cache.get(_CACHE_KEY, _SENTINEL)
    except Exception:  # noqa: BLE001 - any cache backend failure degrades gracefully
        return _load_all()
    if cached is _SENTINEL:
        cached = _load_all()
        try:
            cache.set(_CACHE_KEY, cached, timeout=None)
        except Exception:  # noqa: BLE001
            pass
    return dict(cached)


def get_setting(key: str, default: Any = _SENTINEL) -> Any:
    """Return the effective value of ``key``.

    Resolution order: admin override → spec default. Passing ``default``
    overrides the spec default (useful for keys removed from the registry).
    Raises if the key is unknown and no explicit default is given.
    """
    spec = None
    if default is _SENTINEL:
        spec = get_spec(key)  # raises ValidationError on unknown key
    values = get_all_settings()
    if key in values:
        return values[key]
    if default is not _SENTINEL:
        return default
    return spec.default if spec else None


def invalidate_cache() -> None:
    try:
        cache.delete(_CACHE_KEY)
    except Exception:  # noqa: BLE001 - cache outage must not block writes
        pass
