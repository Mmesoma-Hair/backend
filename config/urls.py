"""Root URL configuration.

The public storefront API lives under ``/api/v1/`` and the admin API under
``/api/v1/admin/`` (role-gated in later phases). Each domain app contributes its
own ``urls.py`` which is included here as the app comes online.
"""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

api_v1_patterns = [
    path("", include("apps.common.urls")),  # health check
    path("auth/", include("apps.accounts.urls")),
    path("config/", include("apps.storeconfig.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("currency/", include("apps.currency.urls")),
    path("cart/", include("apps.cart.urls")),
    path("", include("apps.orders.urls")),
    path("payments/", include("apps.payments.urls")),
]

# Admin API namespace (role-gated to `admin`). Each domain contributes a router.
api_v1_admin_patterns = [
    path("", include("apps.common.admin_urls")),  # audit log
    path("catalog/", include("apps.catalog.admin_urls")),
    path("inventory/", include("apps.inventory.admin_urls")),
    path("currency/", include("apps.currency.admin_urls")),
    path("promotions/", include("apps.promotions.admin_urls")),
    path("", include("apps.orders.admin_urls")),
    path("payments/", include("apps.payments.admin_urls")),
    path("suppliers/", include("apps.suppliers.admin_urls")),
    path("accounts/", include("apps.accounts.admin_urls")),
    path("storeconfig/", include("apps.storeconfig.admin_urls")),
]

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/v1/", include((api_v1_patterns, "api-v1"))),
    path("api/v1/admin/", include((api_v1_admin_patterns, "api-v1-admin"))),
    # OpenAPI schema + docs.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
