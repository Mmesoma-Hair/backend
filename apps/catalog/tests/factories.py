from __future__ import annotations

from decimal import Decimal

import factory

from apps.catalog.models import Category, OptionType, OptionValue, Product, Variant


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    title = factory.Sequence(lambda n: f"Product {n}")
    description = "A product."


def make_size_color_product() -> Product:
    """A product with Size (S,M) × Color (Red,Blue) option types and values."""
    product = ProductFactory(title="Tee")
    size = OptionType.objects.create(product=product, name="Size", position=0)
    color = OptionType.objects.create(product=product, name="Color", position=1)
    OptionValue.objects.create(option_type=size, value="S", position=0)
    OptionValue.objects.create(option_type=size, value="M", position=1)
    OptionValue.objects.create(option_type=color, value="Red", position=0)
    OptionValue.objects.create(option_type=color, value="Blue", position=1)
    return product


class VariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Variant

    product = factory.SubFactory(ProductFactory)
    sku = factory.Sequence(lambda n: f"SKU-{n}")
    price = Decimal("10.00")
