from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.catalog import services
from apps.catalog.models import OptionValue
from apps.inventory.services import set_stock

from .factories import ProductFactory, make_size_color_product


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_product_detail_returns_option_matrix_and_variants(client: APIClient) -> None:
    product = make_size_color_product()
    services.generate_variants(product, default_price=Decimal("19.99"))
    resp = client.get(reverse("api-v1:product-detail", args=[product.slug]))
    assert resp.status_code == 200
    assert len(resp.data["option_types"]) == 2
    assert len(resp.data["variants"]) == 4
    assert resp.data["share_path"] == f"/p/{product.short_id}"


@pytest.mark.django_db
def test_resolve_variant_endpoint(client: APIClient) -> None:
    product = make_size_color_product()
    services.generate_variants(product, default_price=Decimal("19.99"))
    s = OptionValue.objects.get(value="S")
    red = OptionValue.objects.get(value="Red")
    resp = client.post(
        reverse("api-v1:resolve-variant", args=[product.slug]),
        {"option_value_ids": [s.id, red.id]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["sku"]


@pytest.mark.django_db
def test_resolve_variant_invalid_combo_404(client: APIClient) -> None:
    product = make_size_color_product()
    services.generate_variants(product, default_price=Decimal("19.99"))
    resp = client.post(
        reverse("api-v1:resolve-variant", args=[product.slug]),
        {"option_value_ids": [123456]},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_share_link_resolves_by_short_id_unauthenticated(client: APIClient) -> None:
    product = ProductFactory()
    services.ensure_default_variant(product, sku="S1", price=Decimal("9.99"))
    # By short_id and by slug, both without auth.
    by_short = client.get(reverse("api-v1:product-share", args=[product.short_id]))
    by_slug = client.get(reverse("api-v1:product-share", args=[product.slug]))
    assert by_short.status_code == 200
    assert by_slug.status_code == 200
    assert by_short.data["id"] == str(product.id)


@pytest.mark.django_db
def test_variant_in_stock_reflects_inventory(client: APIClient) -> None:
    product = ProductFactory()
    variant = services.ensure_default_variant(product, sku="S1", price=Decimal("9.99"))
    set_stock(variant, 3)
    resp = client.get(reverse("api-v1:product-detail", args=[product.slug]))
    v = resp.data["variants"][0]
    assert v["available"] == 3
    assert v["in_stock"] is True


@pytest.mark.django_db
def test_admin_catalog_requires_admin_role(client: APIClient) -> None:
    # Anonymous and non-admin are both forbidden.
    assert client.get("/api/v1/admin/catalog/products/").status_code in (401, 403)

    customer = UserFactory(role=Role.CUSTOMER, password="Pass12345!")
    client.force_authenticate(customer)
    assert client.get("/api/v1/admin/catalog/products/").status_code == 403


@pytest.mark.django_db
def test_admin_can_generate_variants_via_api(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="Pass12345!")
    client.force_authenticate(admin)
    product = make_size_color_product()
    resp = client.post(
        f"/api/v1/admin/catalog/products/{product.id}/generate-variants/",
        {"default_price": "12.50"},
        format="json",
    )
    assert resp.status_code == 201
    assert len(resp.data) == 4


@pytest.mark.django_db
def test_admin_add_image_then_delete(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="Pass12345!")
    client.force_authenticate(admin)
    product = ProductFactory()
    add = client.post(
        f"/api/v1/admin/catalog/products/{product.id}/images/",
        {"public_id": "eandewigs/products/api-img", "is_primary": True},
        format="json",
    )
    assert add.status_code == 201
    image_id = add.data["id"]
    delete = client.delete(f"/api/v1/admin/catalog/images/{image_id}/")
    assert delete.status_code == 204
