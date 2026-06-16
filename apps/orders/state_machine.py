"""Order status state machine.

Transitions are only allowed along the edges declared here; anything else raises
:class:`InvalidTransition`. The service layer is the sole mutator of
``order.status`` — views never set it directly.
"""

from __future__ import annotations

from apps.common.exceptions import ConflictError

from .models import OrderStatus

S = OrderStatus

ALLOWED: dict[str, set[str]] = {
    S.PENDING: {S.PAID, S.CANCELLED},
    S.PAID: {S.ROUTING, S.REFUNDED, S.CANCELLED},
    S.ROUTING: {S.PARTIALLY_FULFILLED, S.FULFILLED, S.CANCELLED},
    S.PARTIALLY_FULFILLED: {S.FULFILLED, S.REFUNDED},
    S.FULFILLED: {S.COMPLETED, S.REFUNDED},
    S.COMPLETED: {S.REFUNDED},
    S.CANCELLED: set(),
    S.REFUNDED: set(),
}


class InvalidTransition(ConflictError):
    default_code = "invalid_transition"


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED.get(current, set())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(
            f"Cannot move an order from '{current}' to '{target}'.",
            code="invalid_transition",
        )
