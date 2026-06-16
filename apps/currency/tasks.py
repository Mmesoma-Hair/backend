"""Async currency tasks."""

from __future__ import annotations

from celery import shared_task

from . import services


@shared_task
def refresh_exchange_rates() -> dict:
    """Refresh FX rates from the configured provider (Celery Beat schedule)."""
    return services.refresh_rates()
