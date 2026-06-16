"""Generate branded SVG product images and attach them to existing products.

For each product in the catalog this writes an on-brand SVG to the storefront's
``public/products/<slug>.svg`` and ensures the product has a primary
``ProductImage`` whose ``public_id`` (``static/products/<slug>``) resolves to it
via the ``static`` image backend. Re-runnable / idempotent.

    uv run python manage.py generate_product_images          # all products
    uv run python manage.py generate_product_images --force   # overwrite SVGs
"""

from __future__ import annotations

import hashlib
import html
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.catalog.models import Product, ProductImage

# On-brand gradient pairs (all from the burgundy / crimson / ink family).
_PALETTES: list[tuple[str, str]] = [
    ("#6E0D25", "#C9184A"),  # burgundy -> crimson
    ("#1A1A2E", "#6E0D25"),  # ink -> burgundy
    ("#C9184A", "#8A1130"),  # crimson -> deep
    ("#3F0715", "#8A1130"),  # darkest -> mid
    ("#560A1D", "#C9184A"),
]
_BLUSH = "#FFF0F3"


def _palette_for(slug: str) -> tuple[str, str]:
    h = int(hashlib.sha1(slug.encode()).hexdigest(), 16)
    return _PALETTES[h % len(_PALETTES)]


def _icon_for(text: str) -> str:
    """Return a centered line-art icon (stroke=blush) chosen by keyword."""
    t = text.lower()
    stroke = f'fill="none" stroke="{_BLUSH}" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"'
    if any(k in t for k in ("tee", "shirt", "hoodie", "jacket", "sweater")):
        return f"""
  <path d="M430 360 L360 398 L388 474 L432 454 L432 624 L568 624 L568 454 L612 474 L640 398 L570 360
           C548 392 452 392 430 360 Z" {stroke} />"""
    if any(k in t for k in ("mug", "cup", "coffee", "travel")):
        return f"""
  <rect x="392" y="392" width="172" height="226" {stroke} />
  <path d="M564 432 C636 432 636 560 564 560" {stroke} />
  <path d="M430 320 q18 -26 0 -52" {stroke} />
  <path d="M478 320 q18 -26 0 -52" {stroke} />
  <path d="M526 320 q18 -26 0 -52" {stroke} />"""
    if any(k in t for k in ("sticker", "decal", "label", "badge", "pack")):
        return f"""
  <path d="M392 376 L560 376 L608 424 L608 624 L392 624 Z" {stroke} />
  <path d="M560 376 L560 424 L608 424" {stroke} />
  <path d="M500 452 L518 502 L572 504 L530 538 L546 590 L500 560 L454 590 L470 538 L428 504 L482 502 Z" {stroke} />"""
    # Default: shopping bag (echoes the IdealCommerce mark).
    return f"""
  <path d="M398 432 L602 432 L584 632 L416 632 Z" {stroke} />
  <path d="M452 432 C452 372 548 372 548 432" {stroke} />"""


def _svg(product: Product) -> str:
    c1, c2 = _palette_for(product.slug)
    title = html.escape(product.title)
    category = html.escape(product.category.name.upper()) if product.category_id else ""
    brand = html.escape(product.brand.name.upper()) if product.brand_id else ""
    icon = _icon_for(f"{product.title} {product.slug}")

    brand_badge = (
        f'<text x="64" y="96" fill="{_BLUSH}" font-family="Georgia, serif" '
        f'font-size="30" letter-spacing="4" opacity="0.85">{brand}</text>'
        if brand
        else ""
    )
    category_line = (
        f'<text x="500" y="708" text-anchor="middle" fill="{_BLUSH}" '
        f'font-family="Georgia, serif" font-size="26" letter-spacing="6" '
        f'opacity="0.7">{category}</text>'
        if category
        else ""
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000" viewBox="0 0 1000 1000" role="img" aria-label="{title}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{c1}"/>
      <stop offset="1" stop-color="{c2}"/>
    </linearGradient>
  </defs>
  <rect width="1000" height="1000" fill="url(#bg)"/>
  <circle cx="500" cy="470" r="300" fill="{_BLUSH}" opacity="0.06"/>
  <circle cx="500" cy="470" r="210" fill="{_BLUSH}" opacity="0.06"/>
  {icon}
  {brand_badge}
  {category_line}
  <text x="500" y="788" text-anchor="middle" fill="{_BLUSH}" font-family="Georgia, serif" font-size="68" font-weight="700">{title}</text>
  <text x="936" y="952" text-anchor="end" fill="{_BLUSH}" font-family="Georgia, serif" font-size="24" letter-spacing="2" opacity="0.5">idealcommerce</text>
</svg>
"""


class Command(BaseCommand):
    help = "Generate branded SVG images for existing products and attach them."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite SVG files that already exist.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        out_dir = Path(settings.PRODUCT_IMAGE_OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        force: bool = options["force"]

        written = 0
        attached = 0
        products = Product.objects.select_related("category", "brand").order_by("title")
        for product in products:
            path = out_dir / f"{product.slug}.svg"
            if force or not path.exists():
                path.write_text(_svg(product), encoding="utf-8")
                written += 1

            public_id = f"static/products/{product.slug}"
            primary = product.images.filter(variant__isnull=True, is_primary=True).first()
            if primary is None:
                product.images.update(is_primary=False)
                ProductImage.objects.create(
                    product=product,
                    public_id=public_id,
                    alt_text=product.title,
                    is_primary=True,
                )
                attached += 1
            elif primary.public_id != public_id:
                primary.public_id = public_id
                primary.alt_text = primary.alt_text or product.title
                primary.save(update_fields=["public_id", "alt_text", "updated_at"])
                attached += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {written} SVG(s) to {out_dir}; "
                f"attached/updated {attached} primary image(s) across "
                f"{products.count()} product(s)."
            )
        )
