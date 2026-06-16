from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalog import services as catalog_services
from apps.catalog.tests.factories import ProductFactory
from apps.currency import services
from apps.storeconfig import services as config_services

from .factories import seed_basic_currencies


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def currencies(db) -> None:
    seed_basic_currencies()
    services.refresh_rates()
    config_services.set_setting("currency.fx_markup_percent", "0")


@pytest.mark.django_db
def test_currency_list_endpoint(client: APIClient, currencies: None) -> None:
    resp = client.get(reverse("api-v1:currency-list"))
    assert resp.status_code == 200
    assert resp.data["base"] == "USD"
    assert len(resp.data["currencies"]) == 4


@pytest.mark.django_db
def test_rates_endpoint_reports_freshness(client: APIClient, currencies: None) -> None:
    resp = client.get(reverse("api-v1:currency-rates"))
    assert resp.status_code == 200
    assert resp.data["rates"]["EUR"] == "0.92"
    assert resp.data["stale"] is False


@pytest.mark.django_db
def test_product_priced_in_two_currencies(client: APIClient, currencies: None) -> None:
    product = ProductFactory(title="Mug")
    catalog_services.ensure_default_variant(product, sku="MUG-1", price=Decimal("10.00"))

    usd = client.get(reverse("api-v1:product-detail", args=[product.slug]), {"currency": "USD"})
    eur = client.get(reverse("api-v1:product-detail", args=[product.slug]), {"currency": "EUR"})

    usd_price = usd.data["variants"][0]["price_display"]
    eur_price = eur.data["variants"][0]["price_display"]
    assert usd_price["amount"] == "10.00" and usd_price["currency"] == "USD"
    # 10 * 0.92 = 9.20
    assert eur_price["amount"] == "9.20" and eur_price["currency"] == "EUR"
    assert eur_price["base_amount"] == "10.00"


@pytest.mark.django_db
def test_unknown_currency_param_falls_back_to_base(client: APIClient, currencies: None) -> None:
    product = ProductFactory(title="Mug")
    catalog_services.ensure_default_variant(product, sku="MUG-1", price=Decimal("10.00"))
    resp = client.get(reverse("api-v1:product-detail", args=[product.slug]), {"currency": "ZZZ"})
    price = resp.data["variants"][0]["price_display"]
    assert price["currency"] == "USD"  # invalid → base


@pytest.mark.django_db
def test_convert_endpoint(client: APIClient, currencies: None) -> None:
    resp = client.get(reverse("api-v1:currency-convert"), {"amount": "50", "to": "EUR"})
    assert resp.status_code == 200
    assert resp.data["amount"] == "46.00"  # 50 * 0.92
