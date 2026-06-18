"""Unified API error handling.

Every error response uses one envelope so clients can rely on a single shape::

    {"error": {"code": "not_found", "message": "...", "details": {...}}}

``api_exception_handler`` wraps DRF's default handler and also catches Django's
``ValidationError`` / ``Http404`` so service-layer validation surfaces cleanly.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(exceptions.APIException):
    """Base class for business-rule violations raised by services.

    Services raise subclasses of this instead of returning error tuples, so the
    handler can map them to a consistent envelope.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "A domain error occurred."
    default_code = "domain_error"


class GoneError(DomainError):
    status_code = status.HTTP_410_GONE
    default_detail = "This resource is no longer available."
    default_code = "gone"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state."
    default_code = "conflict"


def _build_envelope(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF ``EXCEPTION_HANDLER`` entry point."""
    # Normalize Django-native exceptions into DRF ones first.
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()
    elif isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=getattr(exc, "message_dict", exc.messages))
    elif isinstance(exc, IntegrityError):
        # DB unique/constraint violations (e.g. duplicate SKU) → clean 409
        # instead of a 500, without leaking DB internals to the client.
        exc = ConflictError(
            "This conflicts with an existing record — a value that must be "
            "unique (such as a SKU) is already in use."
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    # Prefer the per-raise code (ErrorDetail.code) over the class default, so
    # services can raise e.g. DomainError("…", code="share_revoked").
    code = _detail_code(getattr(exc, "detail", None)) or getattr(exc, "default_code", "error")
    detail = response.data
    message: str
    details: Any = None

    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = str(detail["detail"])
    elif isinstance(detail, (list, dict)):
        message = _summarize(exc)
        details = detail
    else:
        message = str(detail)

    response.data = _build_envelope(code=str(code), message=message, details=details)
    return response


def _detail_code(detail: Any) -> str | None:
    """Extract the ``code`` from a DRF ErrorDetail (or the first one in a list/dict)."""
    if detail is None:
        return None
    if isinstance(detail, list) and detail:
        return _detail_code(detail[0])
    if isinstance(detail, dict) and detail:
        return _detail_code(next(iter(detail.values())))
    return getattr(detail, "code", None)


def _summarize(exc: Exception) -> str:
    if isinstance(exc, exceptions.ValidationError):
        return "Validation failed."
    return getattr(exc, "default_detail", "An error occurred.")
