from __future__ import annotations

from django.urls import path

from .views import PublicConfigView

urlpatterns = [
    path("", PublicConfigView.as_view(), name="public-config"),
]
