from __future__ import annotations

from unittest import mock

import pytest

from apps.catalog import services
from apps.catalog.images import MockImageBackend, cloudinary_url, image_urls

from .factories import ProductFactory


@pytest.mark.django_db
def test_upload_via_backend_stores_public_id() -> None:
    product = ProductFactory()
    image = services.add_product_image(product, file=b"fake-bytes", alt_text="hero")
    assert image.public_id  # a public_id was returned by the (mock) backend
    assert image.public_id.startswith("eandewigs/products/")


@pytest.mark.django_db
def test_add_image_from_existing_public_id() -> None:
    product = ProductFactory()
    image = services.add_product_image(product, public_id="eandewigs/products/abc")
    assert image.public_id == "eandewigs/products/abc"


def test_delivery_urls_use_auto_format_and_quality() -> None:
    urls = image_urls("eandewigs/products/abc")
    assert set(urls) == {"thumb", "card", "detail"}
    assert "f_auto,q_auto" in cloudinary_url("eandewigs/products/abc", "card")


@pytest.mark.django_db
def test_deleting_image_enqueues_cloudinary_cleanup() -> None:
    product = ProductFactory()
    image = services.add_product_image(product, public_id="eandewigs/products/to-delete")
    # The post_delete signal calls delete_cloudinary_asset.delay(public_id).
    with mock.patch("apps.catalog.signals.delete_cloudinary_asset.delay") as delay:
        image.delete()
    delay.assert_called_once_with("eandewigs/products/to-delete")


@pytest.mark.django_db
def test_deleting_product_cleans_up_its_images() -> None:
    product = ProductFactory()
    services.add_product_image(product, public_id="eandewigs/products/p1")
    services.add_product_image(product, public_id="eandewigs/products/p2")
    with mock.patch("apps.catalog.signals.delete_cloudinary_asset.delay") as delay:
        product.delete()
    assert delay.call_count == 2


def test_upload_signature_shape() -> None:
    sig = services.upload_signature()
    assert {"signature", "timestamp", "api_key", "cloud_name", "folder"} <= set(sig)


def test_mock_backend_roundtrip() -> None:
    backend = MockImageBackend()
    pid = backend.upload(b"x", folder="f")
    assert pid in backend.store
    assert backend.delete(pid) is True
