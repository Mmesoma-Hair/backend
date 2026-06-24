from __future__ import annotations

from decimal import Decimal

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.cart import services as cart_services
from apps.cart.tests.factories import setup_currencies
from apps.catalog.models import FulfillmentType, Product, Variant
from apps.fulfillment import services as fulfillment_services
from apps.fulfillment.models import Shipment, SupplierOrder
from apps.inventory.services import available_quantity, set_stock
from apps.notifications.models import Notification
from apps.orders import services as order_services
from apps.orders.models import OrderStatus
from apps.payments import services as payment_services
from apps.storeconfig import services as config_services
from apps.suppliers.models import Supplier


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _internal_variant(price="20.00", stock=10) -> Variant:
    p = Product.objects.create(title="Internal Item", fulfillment_type=FulfillmentType.INTERNAL)
    v = Variant.objects.create(
        product=p, sku=f"INT-{Variant.objects.count()+1}", price=Decimal(price), is_default=True
    )
    set_stock(v, stock)
    return v


def _dropship_variant(supplier: Supplier, price="15.00") -> Variant:
    p = Product.objects.create(
        title="Dropship Item", fulfillment_type=FulfillmentType.DROPSHIP, supplier=supplier
    )
    return Variant.objects.create(
        product=p, sku=f"DRP-{Variant.objects.count()+1}", price=Decimal(price), is_default=True
    )


def _paid_mixed_order(supplier: Supplier):
    internal = _internal_variant(stock=10)
    dropship = _dropship_variant(supplier)
    cart = cart_services.get_or_create_cart(session_key="mix")
    cart_services.add_item(cart, variant_id=str(internal.id), quantity=2)
    cart_services.add_item(cart, variant_id=str(dropship.id), quantity=1)
    cart_services.set_shipping(cart, {"name": "A", "line1": "1 St", "city": "T", "country": "US"})
    order = order_services.checkout(cart, idempotency_key="mix-1", currency="USD")
    # Pay → triggers routing inline (eager Celery).
    payment_services.confirm_mock_payment(order.payments.first())
    order.refresh_from_db()
    return order, internal, dropship


@pytest.mark.django_db
def test_mixed_order_routes_internal_and_dropship(setup) -> None:
    supplier = Supplier.objects.create(name="Acme", code="acme", adapter="mock")
    order, internal, dropship = _paid_mixed_order(supplier)

    # Internal shipment is created PENDING (admin ships later) but stock is
    # committed now (10 - 2 = 8) — reservations would otherwise expire.
    internal_shipment = order.shipments.get(kind=Shipment.Kind.INTERNAL)
    assert internal_shipment.status == Shipment.Status.PENDING
    assert available_quantity(internal) == 8

    # Dropship: supplier order placed, shipment pending.
    dropship_shipment = order.shipments.get(kind=Shipment.Kind.DROPSHIP)
    assert dropship_shipment.status == Shipment.Status.PENDING
    sup_order = SupplierOrder.objects.get(order=order)
    assert sup_order.supplier_id == supplier.id
    assert sup_order.external_ref

    # Nothing has shipped yet → the order rests in Processing (routing), and no
    # "shipped" email was sent on payment.
    assert order.status == OrderStatus.ROUTING
    assert not Notification.objects.filter(event="shipment_update").exists()


@pytest.mark.django_db
def test_polling_then_admin_ship_reconciles_to_fulfilled(setup) -> None:
    supplier = Supplier.objects.create(name="Acme", code="acme", adapter="mock")
    order, _, _ = _paid_mixed_order(supplier)
    assert order.status == OrderStatus.ROUTING

    # Poll the supplier → dropship shipped. Internal is still pending, so the
    # order is only partially fulfilled.
    updated = fulfillment_services.poll_supplier_orders()
    assert updated == 1
    order.refresh_from_db()
    assert order.status == OrderStatus.PARTIALLY_FULFILLED
    dropship_shipment = order.shipments.get(kind=Shipment.Kind.DROPSHIP)
    assert dropship_shipment.status == Shipment.Status.SHIPPED
    assert dropship_shipment.tracking_number

    # Admin ships the internal portion → order fully fulfilled.
    fulfillment_services.mark_internal_shipped(order)
    order.refresh_from_db()
    assert order.status == OrderStatus.FULFILLED


@pytest.mark.django_db
def test_internal_order_processing_until_admin_marks_shipped(setup) -> None:
    owner = UserFactory(email="buyer@example.com", password="x")
    v = _internal_variant(stock=5)
    cart = cart_services.get_or_create_cart(user=owner)
    cart_services.add_item(cart, variant_id=str(v.id), quantity=1)
    cart_services.set_shipping(cart, {"name": "A", "line1": "1 St", "city": "T", "country": "US"})
    order = order_services.checkout(cart, idempotency_key="int-1", currency="USD")
    payment_services.confirm_mock_payment(order.payments.first())
    order.refresh_from_db()

    # Stock is committed on payment, but the order only ships on an admin action.
    assert order.status == OrderStatus.ROUTING
    assert available_quantity(v) == 4
    assert order.shipments.get(kind=Shipment.Kind.INTERNAL).status == Shipment.Status.PENDING
    assert not Notification.objects.filter(event="shipment_update").exists()

    # Admin marks shipped (with tracking) → email fires + order fulfilled.
    fulfillment_services.mark_internal_shipped(order, tracking_number="TRK1", carrier="DHL")
    order.refresh_from_db()
    assert order.status == OrderStatus.FULFILLED
    shipment = order.shipments.get(kind=Shipment.Kind.INTERNAL)
    assert shipment.status == Shipment.Status.SHIPPED
    assert shipment.tracking_number == "TRK1"
    assert shipment.carrier == "DHL"
    assert Notification.objects.filter(
        event="shipment_update", recipient="buyer@example.com"
    ).exists()
