from __future__ import annotations

from django.urls import path

from .views import ConvertView, CurrencyListView, RatesView

urlpatterns = [
    path("", CurrencyListView.as_view(), name="currency-list"),
    path("rates/", RatesView.as_view(), name="currency-rates"),
    path("convert/", ConvertView.as_view(), name="currency-convert"),
]
