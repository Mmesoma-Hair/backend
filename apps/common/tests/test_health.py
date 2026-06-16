from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_check_returns_ok() -> None:
    client = APIClient()
    response = client.get(reverse("api-v1:health"))
    assert response.status_code == 200
    assert response.data["status"] == "ok"
    assert response.data["checks"]["database"] == "ok"


@pytest.mark.django_db
def test_error_envelope_shape_on_denied_request() -> None:
    # An admin endpoint requires the admin role; an anonymous request is
    # rejected by DRF and must come back in the unified error envelope.
    client = APIClient()
    response = client.get("/api/v1/admin/storeconfig/settings/")
    assert response.status_code in (401, 403)
    assert "error" in response.data
    assert set(response.data["error"]) >= {"code", "message"}
