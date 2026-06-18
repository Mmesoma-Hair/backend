from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .admin_views import AuditLogViewSet
from .analytics_views import AdminAnalyticsView

router = DefaultRouter()
router.register("audit", AuditLogViewSet, basename="admin-audit")

urlpatterns = [
    path("analytics/", AdminAnalyticsView.as_view(), name="admin-analytics"),
    *router.urls,
]
