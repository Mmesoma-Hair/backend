from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ProductImage
from .tasks import delete_cloudinary_asset


@receiver(post_delete, sender=ProductImage)
def cleanup_cloudinary_asset(
    sender: type[ProductImage], instance: ProductImage, **kwargs: Any
) -> None:
    """Enqueue removal of the Cloudinary asset when its DB row is deleted.

    Fires for direct image deletes and for cascade deletes (e.g. deleting a
    product removes its images, each triggering this), so no asset is orphaned.
    """
    if instance.public_id:
        delete_cloudinary_asset.delay(instance.public_id)
