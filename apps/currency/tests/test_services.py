from __future__ import annotations

from decimal import Decimal
from unittest import mock

import pytest

from apps.currency import selectors, services
from apps.currency.models import ExchangeRate
from apps.currency.providers import MockRatesProvider
from apps.currency.services import RateUnavailable
from apps.storeconfig import services as config_services

from .factories import seed_basic_currencies


@pytest.fixture
def currencies(db) -> None:
    seed_basic_currencies()


@pytest.mark.django_db
def test_refresh_rates_writes_db_and_cache(currencies: None) -> None:
    result = services.refresh_rates()
    assert result["ok"] is True
    assert ExchangeRate.objects.filter(base="USD", quote="EUR").exists()
    rates = selectors.get_rates()
    assert rates["USD"] == Decimal("1")
    assert rates["EUR"] == Decimal("0.92")


@pytest.mark.django_db
def test_convert_applies_markup(currencies: None) -> None:
    services.refresh_rates()
    config_services.set_setting("currency.fx_markup_percent", "2.0")
    # 100 USD -> EUR at 0.92 with +2% markup = 100*0.92*1.02 = 93.84
    converted = services.convert(Decimal("100"), "USD", "EUR")
    assert converted == Decimal("93.84")


@pytest.mark.django_db
def test_convert_no_markup_on_base(currencies: None) -> None:
    services.refresh_rates()
    assert services.convert(Decimal("100"), "USD", "USD") == Decimal("100.00")


@pytest.mark.django_db
def test_rounding_increment_and_charm_pricing(currencies: None) -> None:
    services.refresh_rates()
    config_services.set_setting("currency.fx_markup_percent", "0")
    # 1 USD -> NGN at 1500, rounding_increment=1, charm → ...99
    converted = services.convert(Decimal("1"), "USD", "NGN")
    assert converted == Decimal("1499.99")  # 1500 rounded to whole, minus .01


@pytest.mark.django_db
def test_downed_provider_falls_back_to_last_good(currencies: None) -> None:
    services.refresh_rates()  # seed good rates
    good = selectors.get_rates()["EUR"]

    boom = mock.Mock(side_effect=RuntimeError("API down"))
    with mock.patch.object(MockRatesProvider, "fetch_rates", boom):
        result = services.refresh_rates()
    assert result["ok"] is False
    # Conversions still work using the last-good DB rates.
    assert selectors.get_rates()["EUR"] == good
    assert services.convert(Decimal("10"), "USD", "EUR") > 0


@pytest.mark.django_db
def test_convert_unknown_currency_raises(currencies: None) -> None:
    services.refresh_rates()
    with pytest.raises(RateUnavailable):
        services.convert(Decimal("10"), "USD", "XYZ")


@pytest.mark.django_db
def test_price_quote_falls_back_to_base_when_no_rate(currencies: None) -> None:
    # No refresh performed and XYZ unknown → quote falls back to base, converted=False.
    quote = services.price_quote(Decimal("10"), "XYZ")
    assert quote["converted"] is False
    assert quote["currency"] == "USD"


@pytest.mark.django_db
def test_effective_rate_snapshot(currencies: None) -> None:
    services.refresh_rates()
    config_services.set_setting("currency.fx_markup_percent", "2.0")
    rate = services.effective_rate("USD", "EUR")
    # 0.92 * 1.02
    assert rate == Decimal("0.9384")
