"""The typed-settings registry — the heart of the "customize anything" layer.

Every configurable knob is declared here once as a :class:`SettingSpec`: its
section, value type, safe default, and (optionally) a validator. A fresh install
runs entirely off these defaults; admins override individual keys at runtime via
the API and the values are validated back against this registry.

Adding a new configurable knob = adding a spec here. No migration is needed
because values are stored as JSON keyed by name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError

# Logical value types. Stored as JSON; coerced/validated on write.
ValueType = str  # one of the constants below
STRING = "string"
TEXT = "text"
INTEGER = "integer"
DECIMAL = "decimal"
BOOLEAN = "boolean"
JSON = "json"


@dataclass(frozen=True)
class SettingSpec:
    key: str
    section: str
    type: ValueType
    default: Any
    description: str = ""
    # Optional extra validation, raising ValidationError on bad input.
    validator: Callable[[Any], None] | None = field(default=None, compare=False)
    # Secret (e.g. an API key): never returned by the admin API, only "is set".
    secret: bool = False

    def coerce(self, value: Any) -> Any:
        """Coerce a raw (likely JSON/string) value into the declared type."""
        if value is None:
            return None
        try:
            if self.type in (STRING, TEXT):
                return str(value)
            if self.type == INTEGER:
                return int(value)
            if self.type == DECIMAL:
                return str(Decimal(str(value)))  # store as string for exactness
            if self.type == BOOLEAN:
                if isinstance(value, bool):
                    return value
                return str(value).strip().lower() in {"1", "true", "yes", "on"}
            if self.type == JSON:
                return value
        except (ValueError, InvalidOperation) as exc:
            raise ValidationError(f"'{self.key}' expects a {self.type}: {exc}") from exc
        return value

    def validate(self, value: Any) -> Any:
        coerced = self.coerce(value)
        if self.validator is not None and coerced is not None:
            self.validator(coerced)
        return coerced


# --- validators -------------------------------------------------------------
def _currency_code(value: Any) -> None:
    code = str(value).upper()
    if not (len(code) == 3 and code.isalpha()):
        raise ValidationError("Must be a 3-letter ISO 4217 currency code.")


def _currency_list(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError("Must be a non-empty list of currency codes.")
    for code in value:
        _currency_code(code)


def _non_negative_decimal(value: Any) -> None:
    if Decimal(str(value)) < 0:
        raise ValidationError("Must be zero or positive.")


def _payment_provider(value: Any) -> None:
    if str(value) not in {"mock", "paystack", "flutterwave"}:
        raise ValidationError("Must be one of: mock, paystack, flutterwave.")


def _hex_color(value: Any) -> None:
    import re

    if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", str(value)):
        raise ValidationError("Must be a hex colour like #6E0D25.")


# --- the registry -----------------------------------------------------------
SETTINGS: dict[str, SettingSpec] = {
    spec.key: spec
    for spec in (
        # Store identity / branding
        SettingSpec("store.name", "identity", STRING, "Eandewigs", "Public store name."),
        SettingSpec(
            "store.tagline", "identity", STRING, "Shop the world.", "Short marketing tagline."
        ),
        SettingSpec(
            "store.support_email",
            "identity",
            STRING,
            "support@eandewigs.test",
            "Support contact email.",
        ),
        SettingSpec(
            "store.logo_public_id",
            "identity",
            STRING,
            "",
            "Cloudinary public_id of the store logo.",
        ),
        SettingSpec(
            "branding.primary_color",
            "identity",
            STRING,
            "#6E0D25",
            "Primary brand colour (hex) used across the storefront.",
            _hex_color,
        ),
        SettingSpec(
            "branding.accent_color",
            "identity",
            STRING,
            "#C9184A",
            "Accent / call-to-action colour (hex).",
            _hex_color,
        ),
        # Currency
        SettingSpec(
            "currency.base",
            "currency",
            STRING,
            "USD",
            "Base currency all prices are stored in.",
            _currency_code,
        ),
        SettingSpec(
            "currency.enabled",
            "currency",
            JSON,
            ["USD", "EUR", "GBP"],
            "Currencies shoppers may transact in.",
            _currency_list,
        ),
        SettingSpec(
            "currency.fx_markup_percent",
            "currency",
            DECIMAL,
            "2.0",
            "Markup added on top of live FX rates, in percent.",
            _non_negative_decimal,
        ),
        SettingSpec(
            "currency.refresh_minutes",
            "currency",
            INTEGER,
            "60",
            "How often Celery Beat refreshes FX rates (minutes).",
        ),
        # Tax / shipping (rules expanded in later phases)
        SettingSpec(
            "tax.inclusive_pricing", "tax", BOOLEAN, False, "Whether displayed prices include tax."
        ),
        SettingSpec(
            "tax.default_rate_percent",
            "tax",
            DECIMAL,
            "0.0",
            "Fallback tax rate when no zone matches.",
            _non_negative_decimal,
        ),
        SettingSpec(
            "shipping.flat_rate",
            "shipping",
            DECIMAL,
            "0.0",
            "Flat shipping rate in base currency.",
            _non_negative_decimal,
        ),
        SettingSpec(
            "shipping.free_threshold",
            "shipping",
            DECIMAL,
            "0.0",
            "Order subtotal above which shipping is free (0 = disabled).",
            _non_negative_decimal,
        ),
        # Payment
        SettingSpec(
            "payments.providers", "payments", JSON, ["mock"], "Enabled payment provider keys."
        ),
        # Feature flags
        SettingSpec(
            "features.pay_for_a_friend",
            "features",
            BOOLEAN,
            True,
            "Enable shareable carts paid by someone else.",
        ),
        SettingSpec(
            "features.guest_payers",
            "features",
            BOOLEAN,
            True,
            "Allow non-authenticated guests to pay shared carts.",
        ),
        SettingSpec(
            "features.guest_checkout",
            "features",
            BOOLEAN,
            True,
            "Allow guest checkout without an account.",
        ),
        SettingSpec(
            "features.multi_warehouse",
            "features",
            BOOLEAN,
            False,
            "Enable multi-warehouse inventory.",
        ),
        SettingSpec(
            "features.allow_payer_to_set_shipping",
            "features",
            BOOLEAN,
            False,
            "Let the payer set shipping on a shared cart (gift mode).",
        ),
        # Catalog display
        SettingSpec(
            "catalog.hide_out_of_stock",
            "catalog",
            BOOLEAN,
            False,
            "Hide out-of-stock products from the storefront instead of showing them.",
        ),
        # Content blocks
        SettingSpec(
            "content.announcement", "content", TEXT, "", "Site-wide announcement banner text."
        ),
        # Homepage hero (all admin-controlled)
        SettingSpec(
            "hero.badge",
            "hero",
            STRING,
            "New season · 2026 collection",
            "Small pill above the headline.",
        ),
        SettingSpec(
            "hero.headline", "hero", STRING, "Shop the world, pay your way.", "Hero headline."
        ),
        SettingSpec(
            "hero.subtext",
            "hero",
            TEXT,
            "Curated products, live multi-currency pricing, and a checkout you can even share with a friend.",
            "Hero supporting paragraph.",
        ),
        SettingSpec("hero.cta_primary_label", "hero", STRING, "Shop now", "Primary button label."),
        SettingSpec("hero.cta_primary_href", "hero", STRING, "/catalog", "Primary button link."),
        SettingSpec(
            "hero.cta_secondary_label", "hero", STRING, "Explore apparel", "Secondary button label."
        ),
        SettingSpec(
            "hero.cta_secondary_href",
            "hero",
            STRING,
            "/catalog?category=apparel",
            "Secondary button link.",
        ),
        SettingSpec("hero.background_url", "hero", STRING, "", "Background image URL (full URL)."),
        SettingSpec(
            "hero.overlay_opacity",
            "hero",
            INTEGER,
            60,
            "Brand overlay opacity over the background, 0–100 (higher = more tint).",
        ),
        SettingSpec(
            "hero.side_images",
            "hero",
            JSON,
            [],
            "Up to 3 image URLs shown in the hero side stack.",
        ),
        # Chat-to-order — direct customers to Telegram / WhatsApp / phone.
        SettingSpec(
            "order_chat.enabled",
            "ordering",
            BOOLEAN,
            False,
            "Show a 'Chat to order' button on products, cart and checkout.",
        ),
        SettingSpec(
            "order_chat.telegram_url",
            "ordering",
            STRING,
            "",
            "Telegram chat link to direct customers to (e.g. https://t.me/yourhandle).",
        ),
        SettingSpec(
            "order_chat.whatsapp_number",
            "ordering",
            STRING,
            "",
            "WhatsApp number in international format, digits only (e.g. 2348012345678).",
        ),
        SettingSpec(
            "order_chat.phone_number",
            "ordering",
            STRING,
            "",
            "Phone number for the 'Call to order' option (e.g. +2348012345678).",
        ),
        SettingSpec(
            "order_chat.note",
            "ordering",
            STRING,
            "Chat with us to place your order.",
            "Short prompt shown next to the order button.",
        ),
        # Blog AI writer (OpenRouter).
        SettingSpec(
            "blog.openrouter_api_key",
            "blog",
            STRING,
            "",
            "OpenRouter API key for the 'Write with AI' blog feature.",
            secret=True,
        ),
        SettingSpec(
            "blog.ai_model",
            "blog",
            STRING,
            "openai/gpt-4o-mini",
            "OpenRouter model id used to generate blog drafts.",
        ),
        # Payments — managed from the admin Payments page (secrets masked).
        SettingSpec(
            "payments.provider", "payments", STRING, "mock", "Active gateway.", _payment_provider
        ),
        SettingSpec(
            "payments.paystack_secret_key",
            "payments",
            STRING,
            "",
            "Paystack secret key.",
            secret=True,
        ),
        SettingSpec("payments.paystack_public_key", "payments", STRING, "", "Paystack public key."),
        SettingSpec(
            "payments.flutterwave_secret_key",
            "payments",
            STRING,
            "",
            "Flutterwave secret key.",
            secret=True,
        ),
        SettingSpec(
            "payments.flutterwave_public_key", "payments", STRING, "", "Flutterwave public key."
        ),
        SettingSpec(
            "payments.flutterwave_secret_hash",
            "payments",
            STRING,
            "",
            "Flutterwave webhook secret hash (must match the dashboard).",
            secret=True,
        ),
    )
}


# Keys safe to expose to anonymous storefront clients (no operational secrets).
PUBLIC_KEYS: frozenset[str] = frozenset(
    {
        "store.name",
        "store.tagline",
        "store.support_email",
        "store.logo_public_id",
        "branding.primary_color",
        "branding.accent_color",
        "currency.base",
        "currency.enabled",
        "tax.inclusive_pricing",
        "features.pay_for_a_friend",
        "features.guest_payers",
        "features.guest_checkout",
        "catalog.hide_out_of_stock",
        "content.announcement",
        "hero.badge",
        "hero.headline",
        "hero.subtext",
        "hero.cta_primary_label",
        "hero.cta_primary_href",
        "hero.cta_secondary_label",
        "hero.cta_secondary_href",
        "hero.background_url",
        "hero.overlay_opacity",
        "hero.side_images",
        "order_chat.enabled",
        "order_chat.telegram_url",
        "order_chat.whatsapp_number",
        "order_chat.phone_number",
        "order_chat.note",
    }
)


def get_spec(key: str) -> SettingSpec:
    try:
        return SETTINGS[key]
    except KeyError as exc:
        raise ValidationError(f"Unknown setting key: '{key}'.") from exc


def default_for(key: str) -> Any:
    return get_spec(key).default
