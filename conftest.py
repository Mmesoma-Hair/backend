"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Isolate tests: the cache (settings/FX rate maps) must not leak across tests.

    The DB is rolled back per test, but the cache backend is process-global, so we
    clear it around every test to avoid stale cached values.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _clear_notification_outboxes():
    """The in-memory notification channels are process-global; reset per test."""
    from apps.notifications.channels.email import MemoryEmailBackend
    from apps.notifications.channels.telegram import MemoryTelegramBackend

    for backend in (MemoryEmailBackend, MemoryTelegramBackend):
        backend.outbox.clear()
        backend.fail_times = 0
    yield
    for backend in (MemoryEmailBackend, MemoryTelegramBackend):
        backend.outbox.clear()
        backend.fail_times = 0
