"""Admin catalog management API (role: admin), mounted under /api/v1/admin/catalog/."""

from __future__ import annotations

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.common.audit import record_audit
from apps.common.audit_mixins import AuditedModelViewSet
from apps.common.models import AuditLog

from . import services
from .admin_serializers import (
    BrandAdminSerializer,
    CategoryAdminSerializer,
    GenerateVariantsSerializer,
    OptionTypeAdminSerializer,
    OptionValueAdminSerializer,
    ProductAdminSerializer,
    ProductCreateSerializer,
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

    @transaction.atomic
    def perform_create(self, serializer: VariantAdminSerializer) -> None:
        option_value_ids = serializer.validated_data.pop("option_value_ids", None)
        variant = serializer.save()
        if option_value_ids:
            services.set_variant_options(variant, option_value_ids)

    @transaction.atomic
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
    http_method_names = ["get", "delete", "patch", "post"]

    @extend_schema(responses={200: ProductImageSerializer}, tags=["catalog-admin"])
    @action(detail=True, methods=["post"], url_path="make-primary")
    def make_primary(self, request: Request, pk: str | None = None) -> Response:
        image = self.get_object()
        services.set_primary_image(image)
        return Response(ProductImageSerializer(image).data)


class ProductAdminViewSet(_AdminModelViewSet):
    queryset = Product.objects.all().order_by("-created_at").prefetch_related("images", "variants")
    serializer_class = ProductAdminSerializer
    filterset_fields = ["category", "brand", "is_active"]
    search_fields = ["title", "slug", "short_id"]

    @extend_schema(
        request=ProductCreateSerializer,
        responses={201: ProductAdminSerializer},
        tags=["catalog-admin"],
    )
    @action(detail=False, methods=["post"], url_path="create-full")
    def create_full(self, request: Request) -> Response:
        """Create a whole product (details + image + variants + stock) atomically."""
        serializer = ProductCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        product = services.create_product_full(
            title=d["title"],
            description=d.get("description", ""),
            category_id=d.get("category"),
            new_category=d.get("new_category", ""),
            brand_id=d.get("brand"),
            fulfillment_type=d["fulfillment_type"],
            supplier_id=d.get("supplier"),
            is_active=d["is_active"],
            image_public_id=d.get("image_public_id", ""),
            kind=d["kind"],
            sku=d.get("sku"),
            price=d.get("price"),
            stock=d.get("stock", 0),
            options=d.get("options"),
            default_price=d.get("default_price"),
            sku_prefix=d.get("sku_prefix", ""),
            stock_per_variant=d.get("stock_per_variant", 0),
        )
        record_audit(
            actor=request.user,
            action=AuditLog.Action.CREATE,
            target_type="catalog.Product",
            target_id=str(product.id),
            changes={"title": {"after": product.title}},
            metadata={"kind": d["kind"]},
        )
        return Response(
            ProductAdminSerializer(product, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

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
