from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.catalog import selectors, services
from apps.catalog.models import OptionValue, Variant
from apps.common.exceptions import ConflictError, DomainError

from .factories import ProductFactory, make_size_color_product


@pytest.mark.django_db
def test_generate_variants_creates_cartesian_product() -> None:
    product = make_size_color_product()
    created = services.generate_variants(product, default_price=Decimal("19.99"))
    assert len(created) == 4  # 2 sizes × 2 colors
    assert product.variants.count() == 4
    # Each variant has exactly one value per option type.
    for v in created:
        assert v.variant_options.count() == 2


@pytest.mark.django_db
def test_generate_variants_is_idempotent() -> None:
    product = make_size_color_product()
    services.generate_variants(product, default_price=Decimal("19.99"))
    again = services.generate_variants(product, default_price=Decimal("19.99"))
    assert again == []
    assert product.variants.count() == 4


@pytest.mark.django_db
def test_simple_product_gets_one_default_variant() -> None:
    product = ProductFactory()
    variant = services.ensure_default_variant(product, sku="SIMPLE-1", price=Decimal("4.99"))
    assert variant.is_default
    assert variant.options_key == ""
    assert product.variants.count() == 1
    # Calling again returns the same default, not a second one.
    again = services.ensure_default_variant(product, sku="SIMPLE-1", price=Decimal("4.99"))
    assert again.pk == variant.pk


@pytest.mark.django_db
def test_duplicate_combination_rejected_by_db_constraint() -> None:
    product = make_size_color_product()
    s = OptionValue.objects.get(value="S")
    red = OptionValue.objects.get(value="Red")
    key = services.compute_options_key([s.id, red.id])

    Variant.objects.create(product=product, sku="A", price=Decimal("1"), options_key=key)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Variant.objects.create(product=product, sku="B", price=Decimal("1"), options_key=key)


@pytest.mark.django_db
def test_set_variant_options_enforces_one_value_per_type() -> None:
    product = make_size_color_product()
    s = OptionValue.objects.get(value="S")
    m = OptionValue.objects.get(value="M")
    variant = Variant.objects.create(product=product, sku="X", price=Decimal("1"))
    # Two values from the same option type (Size) is invalid.
    with pytest.raises(DomainError):
        services.set_variant_options(variant, [s.id, m.id])


@pytest.mark.django_db
def test_set_variant_options_requires_all_types() -> None:
    product = make_size_color_product()
    s = OptionValue.objects.get(value="S")
    variant = Variant.objects.create(product=product, sku="X", price=Decimal("1"))
    with pytest.raises(DomainError):
        services.set_variant_options(variant, [s.id])  # missing Color


@pytest.mark.django_db
def test_set_variant_options_conflict_on_existing_combo() -> None:
    product = make_size_color_product()
    services.generate_variants(product, default_price=Decimal("5"))
    s = OptionValue.objects.get(value="S")
    red = OptionValue.objects.get(value="Red")
    new_variant = Variant.objects.create(product=product, sku="DUP", price=Decimal("1"))
    with pytest.raises(ConflictError):
        services.set_variant_options(new_variant, [s.id, red.id])


@pytest.mark.django_db
def test_resolve_variant_maps_combination() -> None:
    product = make_size_color_product()
    services.generate_variants(product, default_price=Decimal("5"))
    s = OptionValue.objects.get(value="S")
    blue = OptionValue.objects.get(value="Blue")
    variant = selectors.resolve_variant(product, [s.id, blue.id])
    assert variant is not None
    assert set(selectors.variant_option_value_ids(variant)) == {s.id, blue.id}


@pytest.mark.django_db
def test_resolve_variant_unknown_combination_returns_none() -> None:
    product = make_size_color_product()
    services.generate_variants(product, default_price=Decimal("5"))
    assert selectors.resolve_variant(product, [999999]) is None


@pytest.mark.django_db
def test_effective_fulfillment_type_inherits_from_product() -> None:
    product = ProductFactory(fulfillment_type="dropship")
    variant = Variant.objects.create(product=product, sku="V1", price=Decimal("1"))
    assert variant.effective_fulfillment_type == "dropship"
    assert variant.is_dropship
    variant.fulfillment_type = "internal"
    assert variant.effective_fulfillment_type == "internal"
