"""Admin catalog management API (role: admin), mounted under /api/v1/admin/catalog/."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.common.audit_mixins import AuditedModelViewSet

from . import services
from .admin_serializers import (
    BrandAdminSerializer,
    CategoryAdminSerializer,
    GenerateVariantsSerializer,
    OptionTypeAdminSerializer,
    OptionValueAdminSerializer,
    ProductAdminSerializer,
    ProductImageCreateSerializer,
    UploadSignatureSerializer,
    VariantAdminSerializer,
)
from .models import Brand, Category, OptionType, OptionValue, Product, ProductImage, Variant
from .serializers import ProductImageSerializer, VariantSerializer


class _AdminModelViewSet(AuditedModelViewSet):
    permission_classes = [IsAdminRole]


class CategoryAdminViewSet(_AdminModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategoryAdminSerializer


class BrandAdminViewSet(_AdminModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandAdminSerializer


class OptionTypeAdminViewSet(_AdminModelViewSet):
    queryset = OptionType.objects.all()
    serializer_class = OptionTypeAdminSerializer
    filterset_fields = ["product"]


class OptionValueAdminViewSet(_AdminModelViewSet):
    queryset = OptionValue.objects.all()
    serializer_class = OptionValueAdminSerializer
    filterset_fields = ["option_type"]


class VariantAdminViewSet(_AdminModelViewSet):
    queryset = Variant.objects.all()
    serializer_class = VariantAdminSerializer
    filterset_fields = ["product"]

    def perform_create(self, serializer: VariantAdminSerializer) -> None:
        option_value_ids = serializer.validated_data.pop("option_value_ids", None)
        variant = serializer.save()
        if option_value_ids:
            services.set_variant_options(variant, option_value_ids)

    def perform_update(self, serializer: VariantAdminSerializer) -> None:
        option_value_ids = serializer.validated_data.pop("option_value_ids", None)
        variant = serializer.save()
        if option_value_ids is not None:
            services.set_variant_options(variant, option_value_ids)


class ProductImageAdminViewSet(_AdminModelViewSet):
    """Manage image records. Deleting one removes the Cloudinary asset (via signal)."""

    queryset = ProductImage.objects.all()
    serializer_class = ProductImageSerializer
    filterset_fields = ["product", "variant"]
    http_method_names = ["get", "delete", "patch"]


class ProductAdminViewSet(_AdminModelViewSet):
    queryset = Product.objects.all().order_by("-created_at")
    serializer_class = ProductAdminSerializer
    filterset_fields = ["category", "brand", "is_active"]
    search_fields = ["title", "slug", "short_id"]

    @extend_schema(
        request=GenerateVariantsSerializer,
        responses={201: VariantSerializer(many=True)},
        tags=["catalog-admin"],
    )
    @action(detail=True, methods=["post"], url_path="generate-variants")
    def generate_variants(self, request: Request, pk: str | None = None) -> Response:
        product = self.get_object()
        serializer = GenerateVariantsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = services.generate_variants(
            product,
            default_price=serializer.validated_data["default_price"],
            sku_prefix=serializer.validated_data.get("sku_prefix") or None,
        )
        return Response(VariantSerializer(created, many=True).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=ProductImageCreateSerializer,
        responses={201: ProductImageSerializer},
        tags=["catalog-admin"],
    )
    @action(detail=True, methods=["post"], url_path="images")
    def add_image(self, request: Request, pk: str | None = None) -> Response:
        product = self.get_object()
        serializer = ProductImageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        image = services.add_product_image(
            product,
            public_id=data["public_id"],
            variant=data.get("variant"),
            alt_text=data.get("alt_text", ""),
            position=data.get("position", 0),
            is_primary=data.get("is_primary", False),
        )
        return Response(ProductImageSerializer(image).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=UploadSignatureSerializer, responses={200: dict}, tags=["catalog-admin"])
    @action(detail=False, methods=["post"], url_path="upload-signature")
    def upload_signature(self, request: Request) -> Response:
        """Return signed params so the client can upload directly to Cloudinary."""
        return Response(services.upload_signature())
