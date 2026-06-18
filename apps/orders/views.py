"""Checkout + order endpoints (storefront)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cart import selectors as cart_selectors
from apps.cart import services as cart_services
from apps.cart.models import Cart
from apps.common.exceptions import DomainError

from . import services
from .models import Order
from .serializers import CheckoutSerializer, OrderSerializer, SharedCheckoutSerializer


def _idempotency_key(request: Request) -> str:
    key = request.headers.get("Idempotency-Key") or request.data.get("idempotency_key")
    if not key:
        raise DomainError("An Idempotency-Key header is required.", code="idempotency_required")
    return str(key)


def _session_key(request: Request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _current_cart(request: Request) -> Cart | None:
    user = request.user if request.user and request.user.is_authenticated else None
    session_key = "" if user else _session_key(request)
    return cart_selectors.get_active_cart(user=user, session_key=session_key)


def _order_payload(order: Order) -> dict[str, Any]:
    payment = order.payments.order_by("-created_at").first()
    data = OrderSerializer(order).data
    data["payment"] = (
        {
            "provider": payment.provider,
            "intent_id": payment.intent_id,
            "status": payment.status,
            "authorization_url": payment.authorization_url,
        }
        if payment
        else None
    )
    return data


class CheckoutView(APIView):
    """Owner checkout of their own cart."""

    permission_classes = [AllowAny]

    @extend_schema(request=CheckoutSerializer, responses={201: OrderSerializer}, tags=["checkout"])
    def post(self, request: Request) -> Response:
        key = _idempotency_key(request)
        # Idempotent retry: if this key already produced an order, return it
        # (the cart will have been consumed, so check this before cart emptiness).
        existing = Order.objects.filter(idempotency_key=key).first()
        if existing is not None:
            return Response(_order_payload(existing), status=status.HTTP_201_CREATED)

        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        cart = _current_cart(request)
        if cart is None or not cart.lines.exists():
            raise DomainError("Your cart is empty.", code="empty_cart")

        user = request.user if request.user and request.user.is_authenticated else None
        contact = data.get("contact") or {}
        order = services.checkout(
            cart,
            idempotency_key=key,
            currency=data.get("currency") or None,
            shipping=data.get("shipping") or None,
            address_id=data.get("address_id"),
            save_address=data.get("save_address", False),
            owner_user=user,
            payer_user=user,
            payer_email=contact.get("email", ""),
            payer_name=contact.get("name", ""),
            contact_email=contact.get("email", ""),
            contact_name=contact.get("name", ""),
        )
        return Response(_order_payload(order), status=status.HTTP_201_CREATED)


class SharedCheckoutView(APIView):
    """Pay-for-a-Friend checkout: a payer (other user or guest) pays a shared cart."""

    permission_classes = [AllowAny]

    @extend_schema(
        request=SharedCheckoutSerializer, responses={201: OrderSerializer}, tags=["checkout"]
    )
    def post(self, request: Request, token: str) -> Response:
        key = _idempotency_key(request)
        existing = Order.objects.filter(idempotency_key=key).first()
        if existing is not None:
            return Response(_order_payload(existing), status=status.HTTP_201_CREATED)

        serializer = SharedCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            cart = cart_services.resolve_shared_cart(token)
        except Cart.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not cart.lines.exists():
            raise DomainError("This cart is empty.", code="empty_cart")

        # Shipping: the owner's destination governs; a payer may only set it if allowed.
        shipping = cart.shipping or {}
        if not shipping:
            if cart.allow_payer_to_set_shipping and data.get("shipping"):
                shipping = data["shipping"]
            else:
                raise DomainError(
                    "The cart owner hasn't set a shipping destination.",
                    code="shipping_required",
                )

        payer = data.get("payer") or {}
        user = request.user if request.user and request.user.is_authenticated else None
        if user is None and not payer.get("email"):
            raise DomainError("A payer email is required.", code="payer_required")

        order = services.checkout(
            cart,
            idempotency_key=key,
            currency=data.get("currency") or None,
            shipping=shipping,
            payer_user=user,
            payer_email=payer.get("email", ""),
            payer_name=payer.get("name", ""),
        )
        return Response(_order_payload(order), status=status.HTTP_201_CREATED)


class OrderHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OrderSerializer(many=True)}, tags=["orders"])
    def get(self, request: Request) -> Response:
        from django.db.models import Q

        # Orders the user owns or paid for, plus guest orders (no owner) placed
        # with this account's email — so a checkout made before logging in still
        # appears in their history.
        orders = (
            Order.objects.filter(
                Q(owner=request.user)
                | Q(paid_by_user=request.user)
                | Q(owner__isnull=True, contact_email__iexact=request.user.email)
            )
            .distinct()
            .order_by("-created_at")
        )
        return Response(OrderSerializer(orders, many=True).data)


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OrderSerializer}, tags=["orders"])
    def get(self, request: Request, number: str) -> Response:
        order = Order.objects.filter(number=number).first()
        if order is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        owns = request.user.id in {order.owner_id, order.paid_by_user_id}
        claims_guest = (
            order.owner_id is None
            and bool(order.contact_email)
            and order.contact_email.lower() == (request.user.email or "").lower()
        )
        if not (owns or claims_guest):
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response(_order_payload(order))


class OrderStatusView(APIView):
    """Public, minimal order status by number — used by the post-payment poll.

    Returns only the status (no PII), so a shopper (incl. guests) returning from
    the gateway can wait for the webhook to mark the order paid.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: dict}, tags=["orders"])
    def get(self, request: Request, number: str) -> Response:
        order = Order.objects.filter(number=number).only("number", "status", "paid_at").first()
        if order is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "number": order.number,
                "status": order.status,
                "paid": order.paid_at is not None,
            }
        )
