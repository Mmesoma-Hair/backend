from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.fulfillment.models import Shipment
from apps.notifications.models import Notification
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus
from apps.payments import services as payment_services
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _paid_internal_order(owner) -> Order:
    cart = cart_services.get_or_create_cart(user=owner)
    cart_services.add_item(cart, variant_id=str(make_variant("20.00").id), quantity=1)
    cart_services.set_shipping(cart, {"name": "O", "line1": "1", "city": "T", "country": "US"})
    order = order_services.checkout(cart, idempotency_key="admin-ship-1", currency="USD")
    payment_services.confirm_mock_payment(order.payments.first())
    order.refresh_from_db()
    return order


@pytest.mark.django_db
def test_mark_shipped_requires_admin(setup) -> None:
    owner = UserFactory(email="buyer@example.com", password="x")
    order = _paid_internal_order(owner)
    client = APIClient()
    # Anonymous + non-admin are both rejected.
    assert client.post(f"/api/v1/admin/orders/{order.number}/mark-shipped/").status_code in (
        401,
        403,
    )
    client.force_authenticate(UserFactory(role=Role.CUSTOMER, password="x"))
    assert (
        client.post(f"/api/v1/admin/orders/{order.number}/mark-shipped/").status_code == 403
    )


@pytest.mark.django_db
def test_admin_mark_shipped_ships_internal_and_audits(setup) -> None:
    owner = UserFactory(email="buyer@example.com", password="x")
    order = _paid_internal_order(owner)
    # Paid internal order rests in Processing with a pending shipment; no email yet.
    assert order.status == OrderStatus.ROUTING
    assert not Notification.objects.filter(event="shipment_update").exists()

    client = APIClient()
    client.force_authenticate(UserFactory(role=Role.ADMIN, password="x"))
    resp = client.post(
        f"/api/v1/admin/orders/{order.number}/mark-shipped/",
        {"tracking_number": "TRK123", "carrier": "DHL"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["status"] == OrderStatus.FULFILLED

    shipment = order.shipments.get(kind=Shipment.Kind.INTERNAL)
    assert shipment.status == Shipment.Status.SHIPPED
    assert shipment.tracking_number == "TRK123"
    assert shipment.carrier == "DHL"

    # Shipped email fires once + the action is audit-logged.
    assert Notification.objects.filter(
        event="shipment_update", recipient="buyer@example.com"
    ).exists()
    audit = client.get("/api/v1/admin/audit/?target_type=orders.Order")
    results = audit.data["results"] if isinstance(audit.data, dict) else audit.data
    assert any(e.get("metadata", {}).get("mark_shipped") for e in results)


@pytest.mark.django_db
def test_mark_shipped_is_idempotent(setup) -> None:
    owner = UserFactory(email="buyer@example.com", password="x")
    order = _paid_internal_order(owner)
    client = APIClient()
    client.force_authenticate(UserFactory(role=Role.ADMIN, password="x"))
    url = f"/api/v1/admin/orders/{order.number}/mark-shipped/"

    assert client.post(url, {}, format="json").status_code == 200
    # Second call is a no-op (nothing pending) and doesn't double-send the email.
    assert client.post(url, {}, format="json").status_code == 200
    assert (
        Notification.objects.filter(
            event="shipment_update", recipient="buyer@example.com"
        ).count()
        == 1
    )
