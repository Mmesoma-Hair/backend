"""Async inventory tasks."""

from __future__ import annotations

from celery import shared_task

from . import services


@shared_task
def release_expired_reservations() -> int:
    """Free stock held by reservations whose TTL has elapsed (Celery Beat)."""
    return services.release_expired()
