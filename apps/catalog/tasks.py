"""Async catalog tasks."""

from __future__ import annotations

from celery import shared_task

from .images import get_image_backend


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def delete_cloudinary_asset(self, public_id: str) -> bool:  # type: ignore[no-untyped-def]
    """Remove an orphaned Cloudinary asset.

    Enqueued when a ``ProductImage`` (or its product) is deleted so a DB delete
    never leaves a dangling asset. Retries on transient failures.
    """
    try:
        return get_image_backend().delete(public_id)
    except Exception as exc:  # noqa: BLE001 - retry on any transient backend error
        raise self.retry(exc=exc) from exc
