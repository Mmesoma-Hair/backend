"""Product review services: submit, verified-purchase, rating aggregates."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db.models import Avg, Count

from .models import Product, ProductReview, ReviewStatus


def has_purchased(user: Any, product: Product) -> bool:
    """True if ``user`` has a paid order containing this product."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    from apps.orders.models import Order

    return Order.objects.filter(
        owner=user, paid_at__isnull=False, lines__variant__product=product
    ).exists()


def recompute_rating(product: Product) -> None:
    """Refresh the denormalised rating_avg / rating_count from published reviews."""
    agg = ProductReview.objects.filter(product=product, status=ReviewStatus.PUBLISHED).aggregate(
        avg=Avg("rating"), count=Count("id")
    )
    count = agg["count"] or 0
    avg = Decimal(str(agg["avg"] or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    Product.objects.filter(pk=product.pk).update(rating_avg=avg, rating_count=count)


def submit_review(
    *,
    product: Product,
    user: Any,
    rating: int,
    title: str = "",
    body: str = "",
    author_name: str = "",
) -> ProductReview:
    """Create or update the user's review for a product, then recompute aggregates."""
    name = author_name.strip() or (user.full_name or user.email.split("@")[0])
    review, _ = ProductReview.objects.update_or_create(
        product=product,
        user=user,
        defaults={
            "rating": rating,
            "title": title.strip(),
            "body": body.strip(),
            "author_name": name,
            "is_verified_purchase": has_purchased(user, product),
            "status": ReviewStatus.PUBLISHED,
        },
    )
    recompute_rating(product)
    return review
