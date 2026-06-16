"""Public storefront catalog views (read-only, unauthenticated)."""

from __future__ import annotations

from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.currency.pricing import resolve_currency

from . import selectors
from .models import Category, Variant
from .serializers import (
    CategorySerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ResolveVariantRequestSerializer,
    VariantSerializer,
)


class CategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = CategorySerializer
    pagination_class = None
    queryset = Category.objects.filter(is_active=True)


class ProductListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductListSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {"category__slug": ["exact"], "brand__slug": ["exact"]}
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "price_from", "title"]
    ordering = ["-created_at"]

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return selectors.active_products().prefetch_related(
            "images",
            "option_types",
            Prefetch("variants", queryset=Variant.objects.filter(is_active=True)),
        )

    def get_serializer_context(self) -> dict:
        ctx = super().get_serializer_context()
        ctx["currency"] = resolve_currency(self.request.query_params.get("currency"))
        return ctx


class ProductDetailView(APIView):
    """Product detail by slug: option matrix + variants + shared images."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: ProductDetailSerializer}, tags=["catalog"])
    def get(self, request: Request, slug: str) -> Response:
        product = selectors.get_product_by_slug(slug)
        if product is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        currency = resolve_currency(request.query_params.get("currency"))
        return Response(ProductDetailSerializer(product, context={"currency": currency}).data)


class ProductShareView(APIView):
    """Public share link resolver: /api/v1/catalog/share/<handle> (slug or short_id)."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: ProductDetailSerializer}, tags=["catalog"])
    def get(self, request: Request, handle: str) -> Response:
        product = selectors.get_product_by_share_handle(handle)
        if product is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        currency = resolve_currency(request.query_params.get("currency"))
        return Response(ProductDetailSerializer(product, context={"currency": currency}).data)


class ResolveVariantView(APIView):
    """Map a chosen combination of option values to a variant (or 404)."""

    permission_classes = [AllowAny]

    @extend_schema(
        request=ResolveVariantRequestSerializer,
        responses={200: VariantSerializer},
        tags=["catalog"],
    )
    def post(self, request: Request, slug: str) -> Response:
        product = selectors.get_product_by_slug(slug)
        if product is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ResolveVariantRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = selectors.resolve_variant(product, serializer.validated_data["option_value_ids"])
        if variant is None:
            return Response(
                {
                    "error": {
                        "code": "no_such_variant",
                        "message": "No variant for that combination.",
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        currency = resolve_currency(request.query_params.get("currency"))
        return Response(VariantSerializer(variant, context={"currency": currency}).data)
