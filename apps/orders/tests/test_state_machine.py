from __future__ import annotations

import pytest

from apps.orders.models import Order, OrderStatus
from apps.orders.services import transition
from apps.orders.state_machine import InvalidTransition, can_transition


def test_allowed_and_disallowed_edges() -> None:
    assert can_transition(OrderStatus.PENDING, OrderStatus.PAID)
    assert can_transition(OrderStatus.PAID, OrderStatus.ROUTING)
    assert not can_transition(OrderStatus.PENDING, OrderStatus.FULFILLED)
    assert not can_transition(OrderStatus.CANCELLED, OrderStatus.PAID)


@pytest.mark.django_db
def test_transition_rejects_illegal() -> None:
    order = Order.objects.create(base_currency="USD", currency="USD")
    with pytest.raises(InvalidTransition):
        transition(order, OrderStatus.FULFILLED)  # pending -> fulfilled is illegal


@pytest.mark.django_db
def test_transition_allows_legal() -> None:
    order = Order.objects.create(base_currency="USD", currency="USD")
    transition(order, OrderStatus.PAID)
    order.refresh_from_db()
    assert order.status == OrderStatus.PAID
