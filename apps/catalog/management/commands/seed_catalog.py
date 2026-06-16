"""Seed demo catalog data.

Creates one product with two option types (Size × Color → multiple variants) and
one "simple" product (single default variant), with stock and placeholder images,
so the storefront and variant selector have something to render.

    uv run python manage.py seed_catalog
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog import services
from apps.catalog.models import Brand, Category, FulfillmentType, OptionType, OptionValue, Product
from apps.inventory.services import get_default_warehouse, set_stock
from apps.suppliers.models import Supplier


class Command(BaseCommand):
    help = "Seed demo catalog data (size×color product + a simple product + a dropship product)."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        get_default_warehouse()

        category, _ = Category.objects.get_or_create(slug="apparel", defaults={"name": "Apparel"})
        brand, _ = Brand.objects.get_or_create(slug="idealwear", defaults={"name": "IdealWear"})
        supplier, _ = Supplier.objects.get_or_create(
            code="acme", defaults={"name": "Acme Dropshipping", "adapter": "mock"}
        )

        tshirt = self._seed_tshirt(category, brand)
        sticker = self._seed_simple(category)
        mug = self._seed_dropship(category, supplier)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded: '{tshirt.title}' ({tshirt.variants.count()} variants, /p/{tshirt.short_id}), "
                f"'{sticker.title}' (1 default variant, /p/{sticker.short_id}), "
                f"and dropship '{mug.title}' via {supplier.name} (/p/{mug.short_id})."
            )
        )

    def _seed_dropship(self, category: Category, supplier: Supplier) -> Product:
        product, created = Product.objects.get_or_create(
            slug="travel-mug",
            defaults={
                "title": "Travel Mug",
                "description": "An insulated mug, shipped by our supplier.",
                "category": category,
                "fulfillment_type": FulfillmentType.DROPSHIP,
                "supplier": supplier,
            },
        )
        if not created and product.variants.exists():
            return product
        services.ensure_default_variant(product, sku="MUG-001", price=Decimal("14.99"))
        services.add_product_image(
            product,
            public_id="static/products/travel-mug",
            alt_text="Travel Mug",
            is_primary=True,
        )
        return product

    def _seed_tshirt(self, category: Category, brand: Brand) -> Product:
        product, created = Product.objects.get_or_create(
            slug="classic-tee",
            defaults={
                "title": "Classic Tee",
                "description": "A comfy cotton t-shirt.",
                "category": category,
                "brand": brand,
            },
        )
        if not created and product.variants.exists():
            return product

        size = OptionType.objects.create(product=product, name="Size", position=0)
        color = OptionType.objects.create(product=product, name="Color", position=1)
        for i, v in enumerate(["S", "M", "L"]):
            OptionValue.objects.create(option_type=size, value=v, position=i)
        for i, v in enumerate(["Red", "Blue"]):
            OptionValue.objects.create(option_type=color, value=v, position=i)

        variants = services.generate_variants(
            product, default_price=Decimal("19.99"), sku_prefix="TEE"
        )
        # Add a product-level placeholder image (mock public_id in dev).
        services.add_product_image(
            product,
            public_id="static/products/classic-tee",
            alt_text="Classic Tee",
            is_primary=True,
        )
        for variant in variants:
            set_stock(variant, 25)
        return product

    def _seed_simple(self, category: Category) -> Product:
        product, created = Product.objects.get_or_create(
            slug="sticker-pack",
            defaults={
                "title": "Sticker Pack",
                "description": "A pack of vinyl stickers.",
                "category": category,
            },
        )
        if not created and product.variants.exists():
            return product

        variant = services.ensure_default_variant(product, sku="STICKER-001", price=Decimal("4.99"))
        services.add_product_image(
            product,
            public_id="static/products/sticker-pack",
            alt_text="Sticker Pack",
            is_primary=True,
        )
        set_stock(variant, 100)
        return product
