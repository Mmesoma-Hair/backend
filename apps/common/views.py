"""Cross-cutting endpoints — currently the health check."""

from __future__ import annotations

from typing import Any

from django.db import connections
from django.db.utils import OperationalError
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """Liveness/readiness probe.

    Returns 200 when the process is up. Database connectivity is reported in the
    payload so orchestrators can distinguish "process alive" from "fully ready".
    """

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        responses={200: dict, 503: dict},
        summary="Service health check",
        tags=["health"],
    )
    def get(self, request: Request) -> Response:
        db_ok = self._check_database()
        payload = {
            "status": "ok" if db_ok else "degraded",
            "service": "eandewigs-backend",
            "checks": {"database": "ok" if db_ok else "error"},
        }
        code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=code)

    @staticmethod
    def _check_database() -> bool:
        try:
            connections["default"].cursor()
        except OperationalError:
            return False
        return True
