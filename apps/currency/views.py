"""Public currency endpoints."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import selectors, services
from .models import Currency
from .serializers import CurrencySerializer


class CurrencyListView(generics.ListAPIView):
    """Active currencies + which one is the base."""

    permission_classes = [AllowAny]
    serializer_class = CurrencySerializer
    pagination_class = None

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return Currency.objects.filter(is_active=True)

    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        data = self.get_serializer(self.get_queryset(), many=True).data
        return Response({"base": selectors.base_code(), "currencies": data})


class RatesView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict}, tags=["currency"])
    def get(self, request: Request) -> Response:
        rates = {code: str(rate) for code, rate in selectors.get_rates().items()}
        return Response({"rates": rates, **selectors.rates_status()})


class ConvertView(APIView):
    """Convenience conversion endpoint: ?amount=&from=&to=."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict}, tags=["currency"])
    def get(self, request: Request) -> Response:
        try:
            amount = Decimal(request.query_params.get("amount", "0"))
        except (InvalidOperation, TypeError):
            return Response(
                {"error": {"code": "invalid_amount", "message": "amount must be a number."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from_code = request.query_params.get("from") or selectors.base_code()
        to_code = request.query_params.get("to") or selectors.base_code()
        result = (
            services.price_quote(amount, to_code) if from_code == selectors.base_code() else None
        )
        if result is None:
            converted = services.convert(amount, from_code, to_code)
            result = {
                "base_amount": str(amount),
                "currency": to_code.upper(),
                "amount": str(converted),
            }
        return Response(result)
