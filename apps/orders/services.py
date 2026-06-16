"""Order business logic: state transitions and checkout (cart → order).

Checkout snapshots prices and the FX rate, reserves stock, and creates a payment
intent — all idempotent on the supplied key. Order ownership always stays with
the cart owner; a payer (Pay for a Friend) is recorded separately.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.cart.models import Cart
from apps.cart.selectors import validate_cart
from apps.common.exceptions import DomainError
from apps.currency import selectors as currency_selectors
from apps.currency import services as currency_services
from apps.inventory import services as inventory_services
from apps.promotions import services as promo_services
from apps.promotions.models import Coupon

from .models import Order, OrderLine, OrderStatus
from .state_machine import assert_transition

BLOCKING_ISSUES = {"insufficient_stock", "inactive"}


@transaction.atomic
def transition(order: Order, target: str, *, save: bool = True) -> Order:
    assert_transition(order.status, target)
    order.status = target
    if save:
        order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def mark_paid(
    order: Order,
    *,
    paid_by_user: Any = None,
    payer_email: str = "",
    payer_name: str = "",
) -> Order:
    """Move PENDING → PAID, record payer + timestamp, bump coupon usage.

    The fulfillment routing engine (Phase 7) hooks ``order.paid`` from here.
    """
    assert_transition(order.status, OrderStatus.PAID)
    order.status = OrderStatus.PAID
    order.paid_at = timezone.now()
    if paid_by_user is not None and getattr(paid_by_user, "is_authenticated", False):
        order.paid_by_user = paid_by_user
        order.payer_email = order.payer_email or getattr(paid_by_user, "email", "")
    if payer_email:
        order.payer_email = payer_email
    if payer_name:
        order.payer_name = payer_name
    order.save()

    if order.coupon_codes:
        Coupon.objects.filter(code__in=order.coupon_codes).update(used_count=F("used_count") + 1)
    _on_paid(order)
    return order


def _on_paid(order: Order) -> None:
    """Hook called after an order is paid: trigger fulfillment routing.

    Local import avoids a circular dependency (fulfillment imports orders). When
    Celery runs eagerly (dev/tests) we route inline; otherwise we defer to
    ``on_commit`` so the worker only sees a committed order.
    """
    from django.conf import settings

    from apps.fulfillment.tasks import route_order_task
    from apps.notifications.notify import on_order_paid

    order_id = str(order.id)
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        route_order_task(order_id)
    else:
        transaction.on_commit(lambda: route_order_task.delay(order_id))

    # Customer confirmation + ops alert (best-effort; never blocks payment).
    on_order_paid(order)


@transaction.atomic
def checkout(
    cart: Cart,
    *,
    idempotency_key: str,
    currency: str | None = None,
    shipping: dict[str, Any] | None = None,
    owner_user: Any = None,
    payer_user: Any = None,
    payer_email: str = "",
    payer_name: str = "",
    contact_email: str = "",
    contact_name: str = "",
) -> Order:
    """Create an order from a cart (idempotent), reserving stock and locking FX.

    Ownership is ``cart.owner`` when set; otherwise, for a normal (non-shared)
    checkout, the authenticated ``owner_user`` claims the guest cart so the order
    shows up in their account. ``payer_*`` records who is paying (never owner).
    """
    if not idempotency_key:
        raise DomainError("An idempotency key is required.", code="idempotency_required")
    existing = Order.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing

    lines = list(
        cart.lines.select_related("variant", "variant__product", "variant__product__category")
    )
    if not lines:
        raise DomainError("Cart is empty.", code="empty_cart")

    blocking = [i for i in validate_cart(cart) if i["code"] in BLOCKING_ISSUES]
    if blocking:
        raise DomainError("Some items are unavailable.", code="cart_invalid")

    base = currency_selectors.base_code()
    display = (currency or cart.currency or base).upper()
    if display not in set(currency_selectors.active_codes()):
        display = base
    locked_rate = currency_services.effective_rate(base, display)

    subtotal_base = Decimal("0")
    category_subtotals: dict[int, Decimal] = {}
    for line in lines:
        line_base = line.variant.price * line.quantity
        subtotal_base += line_base
        cat_id = line.variant.product.category_id
        if cat_id is not None:
            category_subtotals[cat_id] = category_subtotals.get(cat_id, Decimal("0")) + line_base

    discounts = promo_services.compute_discounts(
        list(cart.coupons.all()),
        subtotal=subtotal_base,
        category_subtotals=category_subtotals,
        user=cart.owner,
    )
    discount_base = discounts["total"]
    total_base = max(subtotal_base - discount_base, Decimal("0"))

    def charged(amount: Decimal) -> Decimal:
        return currency_services.convert(amount, base, display, rate=locked_rate)

    owner = cart.owner
    if owner is None and owner_user is not None and getattr(owner_user, "is_authenticated", False):
        owner = owner_user
    if owner is not None:
        contact_email = contact_email or owner.email
        contact_name = contact_name or owner.full_name

    ship = shipping if shipping else (cart.shipping or {})

    order = Order.objects.create(
        owner=owner,
        contact_email=contact_email,
        contact_name=contact_name,
        paid_by_user=(
            payer_user if (payer_user and getattr(payer_user, "is_authenticated", False)) else None
        ),
        payer_email=payer_email,
        payer_name=payer_name,
        base_currency=base,
        currency=display,
        fx_rate_locked=locked_rate,
        subtotal_base=subtotal_base,
        discount_base=discount_base,
        total_base=total_base,
        subtotal_charged=charged(subtotal_base),
        discount_charged=charged(discount_base),
        total_charged=charged(total_base),
        ship_name=ship.get("name", ""),
        ship_line1=ship.get("line1", ""),
        ship_line2=ship.get("line2", ""),
        ship_city=ship.get("city", ""),
        ship_region=ship.get("region", ""),
        ship_postal_code=ship.get("postal_code", ""),
        ship_country=ship.get("country", ""),
        ship_phone=ship.get("phone", ""),
        coupon_codes=[c.code for c in cart.coupons.all()],
        idempotency_key=idempotency_key,
    )

    for line in lines:
        line_base = line.variant.price * line.quantity
        order_line = OrderLine.objects.create(
            order=order,
            variant=line.variant,
            sku=line.variant.sku,
            title=line.variant.product.title,
            quantity=line.quantity,
            unit_price_base=line.variant.price,
            line_total_base=line_base,
            unit_price_charged=charged(line.variant.price),
            line_total_charged=charged(line_base),
            fulfillment_type=line.variant.effective_fulfillment_type,
        )
        # Hold stock per line (reference includes the line id) so fulfillment can
        # consume/release each line independently.
        inventory_services.reserve(
            line.variant,
            line.quantity,
            reference=f"order:{order.id}:{order_line.id}",
            ttl_minutes=60,
        )

    # Create the payment intent (idempotent on a derived key).
    from apps.payments import services as payment_services

    payment_services.create_payment_for_order(
        order,
        idempotency_key=f"{idempotency_key}:pay",
        payer_user=payer_user,
        payer_email=payer_email or contact_email,
        payer_name=payer_name or contact_name,
    )

    cart.status = Cart.Status.ORDERED
    cart.save(update_fields=["status", "updated_at"])
    return order
