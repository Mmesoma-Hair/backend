"""Thin views for store configuration.

A public read endpoint exposes only storefront-safe keys; full admin management
(all keys, writes) is role-gated under ``/api/v1/admin/storeconfig/``. Writes go
through the service layer, which validates and audit-logs each change.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole

from . import selectors, services
from .schema import PUBLIC_KEYS, SETTINGS
from .serializers import (
    BulkSettingsWriteSerializer,
    SettingSpecSerializer,
    SettingWriteSerializer,
)


class PublicConfigView(views.APIView):
    """GET storefront-safe settings as a flat ``{key: value}`` map."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: dict}, tags=["storeconfig"])
    def get(self, request: Request) -> Response:
        values = selectors.get_all_settings()
        public = {k: v for k, v in values.items() if k in PUBLIC_KEYS}
        return Response({"settings": public})


def _spec_dict(spec, values: dict) -> dict:
    stored = values.get(spec.key, spec.default)
    item = {
        "key": spec.key,
        "section": spec.section,
        "type": spec.type,
        "description": spec.description,
        "default": "" if spec.secret else spec.default,
        "secret": spec.secret,
    }
    if spec.secret:
        # Never return a secret value — only whether one is set.
        item["value"] = ""
        item["is_set"] = bool(stored)
    else:
        item["value"] = stored
    return item


def _spec_payload() -> list[dict]:
    values = selectors.get_all_settings()
    return [_spec_dict(spec, values) for spec in SETTINGS.values()]


class AdminSettingsView(views.APIView):
    """List every setting spec, or bulk-update values (role: admin)."""

    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: SettingSpecSerializer(many=True)}, tags=["storeconfig-admin"])
    def get(self, request: Request) -> Response:
        return Response({"settings": _spec_payload()})

    @extend_schema(
        request=BulkSettingsWriteSerializer, responses={200: dict}, tags=["storeconfig-admin"]
    )
    def patch(self, request: Request) -> Response:
        serializer = BulkSettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_many(serializer.validated_data["values"], actor=request.user)
        return Response({"settings": _spec_payload()})


class AdminSettingDetailView(views.APIView):
    """Read/update/reset a single setting by key (role: admin)."""

    permission_classes = [IsAdminRole]

    @extend_schema(
        request=SettingWriteSerializer,
        responses={200: SettingSpecSerializer},
        tags=["storeconfig-admin"],
    )
    def put(self, request: Request, key: str) -> Response:
        if key not in SETTINGS:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = SettingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Spec validation (type coercion + validators) happens in the service and
        # surfaces as a 400 via the unified exception handler on bad input.
        services.set_setting(key, serializer.validated_data["value"], actor=request.user)
        return Response(_single_payload(key))

    @extend_schema(responses={204: None}, tags=["storeconfig-admin"])
    def delete(self, request: Request, key: str) -> Response:
        if key not in SETTINGS:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.reset_setting(key, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _single_payload(key: str) -> dict:
    spec = SETTINGS[key]
    return _spec_dict(spec, {key: selectors.get_setting(key)})
