"""Pluggable product-image storage/delivery (Cloudinary by default).

All image bytes live in Cloudinary; the DB only stores the ``public_id``. A
backend interface keeps the SDK calls in one place and lets tests/local dev swap
in a network-free :class:`MockImageBackend`.

Delivery URLs are built with auto format/quality (``f_auto``/``q_auto``) and a
small set of named size variants so the storefront/CDN does the resizing.
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from typing import Any, BinaryIO

from django.conf import settings

# Named delivery sizes. Each maps to Cloudinary transformation params.
IMAGE_VARIANTS: dict[str, dict[str, Any]] = {
    "thumb": {"width": 150, "height": 150, "crop": "fill"},
    "card": {"width": 400, "height": 400, "crop": "fill"},
    "detail": {"width": 1000, "crop": "limit"},
}
_BASE_TRANSFORM = {"fetch_format": "auto", "quality": "auto"}


class BaseImageBackend(ABC):
    @abstractmethod
    def upload(
        self, file: BinaryIO | bytes | str, *, folder: str, public_id: str | None = None
    ) -> str:
        """Store an asset and return its ``public_id``."""

    @abstractmethod
    def delete(self, public_id: str) -> bool:
        """Remove an asset. Returns True if it was deleted (or already gone)."""

    @abstractmethod
    def build_url(self, public_id: str, variant: str = "card") -> str:
        """Build a delivery URL for the given named size variant."""

    @abstractmethod
    def signature(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return signed params for a client-side (signed) direct upload."""


class CloudinaryBackend(BaseImageBackend):
    """Talks to the real Cloudinary account via the SDK."""

    def __init__(self) -> None:
        import cloudinary  # local import so the dependency is optional in tests

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )
        self._cloudinary = cloudinary

    def upload(
        self, file: BinaryIO | bytes | str, *, folder: str, public_id: str | None = None
    ) -> str:
        import cloudinary.uploader

        result = cloudinary.uploader.upload(file, folder=folder, public_id=public_id)
        return str(result["public_id"])

    def delete(self, public_id: str) -> bool:
        import cloudinary.uploader

        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") in {"ok", "not found"}

    def build_url(self, public_id: str, variant: str = "card") -> str:
        from cloudinary import CloudinaryImage

        transform = {**_BASE_TRANSFORM, **IMAGE_VARIANTS.get(variant, IMAGE_VARIANTS["card"])}
        return str(CloudinaryImage(public_id).build_url(**transform))

    def signature(self, params: dict[str, Any]) -> dict[str, Any]:
        import cloudinary.utils

        timestamp = int(time.time())
        to_sign = {"timestamp": timestamp, **params}
        signature = cloudinary.utils.api_sign_request(to_sign, settings.CLOUDINARY_API_SECRET)
        return {
            "signature": signature,
            "timestamp": timestamp,
            "api_key": settings.CLOUDINARY_API_KEY,
            "cloud_name": settings.CLOUDINARY_CLOUD_NAME,
            **params,
        }


class MockImageBackend(BaseImageBackend):
    """In-memory backend for tests / key-less local dev. Never hits the network."""

    # Class-level store so assertions can inspect uploads across instances.
    store: dict[str, bytes | str] = {}

    def upload(
        self, file: BinaryIO | bytes | str, *, folder: str, public_id: str | None = None
    ) -> str:
        pid = public_id or hashlib.sha1(f"{folder}:{time.time_ns()}".encode()).hexdigest()[:16]
        full = f"{folder}/{pid}"
        self.store[full] = file if isinstance(file, (bytes, str)) else b"<stream>"
        return full

    def delete(self, public_id: str) -> bool:
        self.store.pop(public_id, None)
        return True

    def build_url(self, public_id: str, variant: str = "card") -> str:
        size = variant if variant in IMAGE_VARIANTS else "card"
        return f"https://mock.cloudinary.local/{size}/f_auto,q_auto/{public_id}"

    def signature(self, params: dict[str, Any]) -> dict[str, Any]:
        timestamp = int(time.time())
        return {
            "signature": "mock-signature",
            "timestamp": timestamp,
            "api_key": "mock-key",
            "cloud_name": "mock-cloud",
            **params,
        }


class StaticImageBackend(MockImageBackend):
    """Serve generated product images from the storefront's ``/public`` folder.

    Used for local dev / demos when there's no Cloudinary account: the
    ``generate_product_images`` command writes branded SVGs to the storefront's
    ``public/products/<leaf>.svg`` and this backend maps a stored ``public_id``
    (e.g. ``static/products/classic-tee``) to the matching delivery URL. SVGs
    scale freely, so every named size variant points at the same asset.
    """

    def build_url(self, public_id: str, variant: str = "card") -> str:
        leaf = public_id.rsplit("/", 1)[-1]
        base = str(getattr(settings, "STATIC_IMAGE_BASE_URL", "")).rstrip("/")
        return f"{base}/products/{leaf}.svg"


_BACKENDS = {
    "cloudinary": CloudinaryBackend,
    "mock": MockImageBackend,
    "static": StaticImageBackend,
}


def get_image_backend() -> BaseImageBackend:
    name = getattr(settings, "CATALOG_IMAGE_BACKEND", "mock")
    backend_cls = _BACKENDS.get(name, MockImageBackend)
    return backend_cls()


def _backend_for(public_id: str) -> BaseImageBackend:
    """Pick the delivery backend for a stored ``public_id``.

    Locally generated demo placeholders are stored as ``static/...`` and are
    always served from the storefront's ``/public`` folder, regardless of the
    configured backend — so switching uploads to Cloudinary never breaks them.
    Everything else (real uploads) uses the configured backend.
    """
    if public_id.startswith("static/"):
        return StaticImageBackend()
    return get_image_backend()


def cloudinary_url(public_id: str, variant: str = "card") -> str:
    """Convenience: build a delivery URL for a stored public_id."""
    return _backend_for(public_id).build_url(public_id, variant)


def image_urls(public_id: str) -> dict[str, str]:
    """All named-variant URLs for a public_id (what serializers expose)."""
    backend = _backend_for(public_id)
    return {name: backend.build_url(public_id, name) for name in IMAGE_VARIANTS}
