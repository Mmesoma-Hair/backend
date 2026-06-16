from __future__ import annotations

from django.urls import path

from .views import (
    CategoryListView,
    ProductDetailView,
    ProductListView,
    ProductShareView,
    ResolveVariantView,
)

urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("products/", ProductListView.as_view(), name="product-list"),
    path("products/<slug:slug>/", ProductDetailView.as_view(), name="product-detail"),
    path(
        "products/<slug:slug>/resolve-variant/",
        ResolveVariantView.as_view(),
        name="resolve-variant",
    ),
    path("share/<str:handle>/", ProductShareView.as_view(), name="product-share"),
]
