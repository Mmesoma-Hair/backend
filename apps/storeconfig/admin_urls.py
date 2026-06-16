from __future__ import annotations

from django.urls import path

from .views import AdminSettingDetailView, AdminSettingsView

urlpatterns = [
    path("settings/", AdminSettingsView.as_view(), name="admin-settings"),
    path("settings/<str:key>/", AdminSettingDetailView.as_view(), name="admin-setting-detail"),
]
