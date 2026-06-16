"""Storefront cart endpoints (work for both authenticated users and guests)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import selectors, services
from .models import Cart
from .serializers import (
    AddItemSerializer,
    ApplyCouponSerializer,
    CreateShareSerializer,
    UpdateItemSerializer,
)


def _session_key(request: Request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _current_cart(request: Request, *, create: bool = False) -> Cart | None:
    user = request.user if request.user and request.user.is_authenticated else None
    session_key = "" if user else _session_key(request)
    if create:
        return services.get_or_create_cart(user=user, session_key=session_key)
    return selectors.get_active_cart(user=user, session_key=session_key)


def _cart_payload(request: Request, cart: Cart) -> dict[str, Any]:
    currency = request.query_params.get("currency")
    totals = selectors.compute_cart_totals(cart, currency=currency)
    return {
        "id": str(cart.id),
        **totals,
        "issues": selectors.validate_cart(cart),
        "shipping": cart.shipping,
        "share": {
            "is_shared": cart.is_shared,
            "token": cart.share_token if cart.is_shared else None,
            "expires_at": cart.share_expires_at,
            "allow_payer_to_set_shipping": cart.allow_payer_to_set_shipping,
        },
    }


class CartView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict}, tags=["cart"])
    def get(self, request: Request) -> Response:
        cart = _current_cart(request, create=True)
        return Response(_cart_payload(request, cart))


class CartItemsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=AddItemSerializer, responses={201: dict}, tags=["cart"])
    def post(self, request: Request) -> Response:
        serializer = AddItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = _current_cart(request, create=True)
        services.add_item(
            cart,
            variant_id=str(serializer.validated_data["variant"]),
            quantity=serializer.validated_data["quantity"],
        )
        return Response(_cart_payload(request, cart), status=status.HTTP_201_CREATED)


class CartItemDetailView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=UpdateItemSerializer, responses={200: dict}, tags=["cart"])
    def patch(self, request: Request, line_id: str) -> Response:
        serializer = UpdateItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = _require_cart(request)
        services.update_item(cart, line_id=line_id, quantity=serializer.validated_data["quantity"])
        return Response(_cart_payload(request, cart))

    @extend_schema(responses={200: dict}, tags=["cart"])
    def delete(self, request: Request, line_id: str) -> Response:
        cart = _require_cart(request)
        services.remove_item(cart, line_id=line_id)
        return Response(_cart_payload(request, cart))


class CartCouponsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=ApplyCouponSerializer, responses={200: dict}, tags=["cart"])
    def post(self, request: Request) -> Response:
        serializer = ApplyCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = _current_cart(request, create=True)
        services.apply_coupon(cart, code=serializer.validated_data["code"])
        return Response(_cart_payload(request, cart))


class CartCouponDetailView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict}, tags=["cart"])
    def delete(self, request: Request, code: str) -> Response:
        cart = _require_cart(request)
        services.remove_coupon(cart, code=code)
        return Response(_cart_payload(request, cart))


class CartShippingView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=dict, responses={200: dict}, tags=["cart"])
    def put(self, request: Request) -> Response:
        cart = _current_cart(request, create=True)
        services.set_shipping(cart, request.data or {})
        return Response(_cart_payload(request, cart))


class CartShareView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=CreateShareSerializer, responses={200: dict}, tags=["cart"])
    def post(self, request: Request) -> Response:
        serializer = CreateShareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = _current_cart(request, create=True)
        services.create_share(
            cart, expires_in_hours=serializer.validated_data.get("expires_in_hours")
        )
        return Response(_cart_payload(request, cart))

    @extend_schema(responses={200: dict}, tags=["cart"])
    def delete(self, request: Request) -> Response:
        cart = _require_cart(request)
        services.revoke_share(cart)
        return Response(_cart_payload(request, cart))


class SharedCartView(APIView):
    """Public, read-only view of a shared cart. Exposes only contents + totals.

    Never reveals the owner's identity, address, payment methods, or history.
    Returns 410 Gone for a revoked/expired link, 404 for an unknown token.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: dict}, tags=["cart"])
    def get(self, request: Request, token: str) -> Response:
        try:
            cart = services.resolve_shared_cart(token)
        except Cart.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        currency = request.query_params.get("currency")
        totals = selectors.compute_cart_totals(cart, currency=currency)
        return Response(
            {
                "token": token,
                **totals,
                "allow_payer_to_set_shipping": cart.allow_payer_to_set_shipping,
            }
        )


def _require_cart(request: Request) -> Cart:
    cart = _current_cart(request)
    if cart is None:
        from apps.common.exceptions import DomainError

        raise DomainError("No active cart.", code="no_cart")
    return cart
