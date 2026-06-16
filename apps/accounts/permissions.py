"""Role-based DRF permission classes.

Authorization keys off ``user.role`` (not ``is_staff``). Use these explicitly on
protected views rather than relying on a global default, so intent is always
visible at the view.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .models import Role


class _RolePermission(BasePermission):
    role: str

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.role == self.role)


class IsAdminRole(_RolePermission):
    """Grants access only to users with the ``admin`` role."""

    role = Role.ADMIN


class IsSupplier(_RolePermission):
    role = Role.SUPPLIER


class IsCustomer(_RolePermission):
    role = Role.CUSTOMER
