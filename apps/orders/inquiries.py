"""Chat-to-order inquiries.

Builds a human-readable order summary for the chosen channel (Telegram /
WhatsApp / Call), persists the lead, and — when the store's Telegram bot is
configured — pushes it to the ops chat in real time. The frontend uses the
returned deep links to open Telegram / WhatsApp / the dialer.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from django.conf import settings

from apps.cart.selectors import compute_cart_totals
from apps.catalog.models import Variant
from apps.storeconfig import selectors as config_selectors

from .models import OrderInquiry


def _cfg(key: str) -> str:
    return config_selectors.get_setting(key, "") or ""


def _store_name() -> str:
    return _cfg("store.name") or "the store"


def _frontend_base() -> str:
    return str(getattr(settings, "FRONTEND_BASE_URL", "")).rstrip("/")


def _variant_label(variant: Variant) -> str:
    parts = [vo.option_value.value for vo in variant.variant_options.all()]
    return " / ".join(parts)


def build_product_summary(variant: Variant, quantity: int) -> str:
    product = variant.product
    qty = max(int(quantity or 1), 1)
    from apps.currency import selectors as currency_selectors
    from apps.currency import services as currency_services

    code = currency_selectors.base_code()
    unit = currency_services.price_quote(variant.effective_price, code).get("formatted")
    line_total = currency_services.price_quote(variant.effective_price * qty, code).get("formatted")

    lines = [f"🛍️ *Order inquiry* — {_store_name()}", "", f"Product: {product.title}"]
    label = _variant_label(variant)
    if label:
        lines.append(f"Option: {label}")
    lines.append(f"SKU: {variant.sku}")
    lines.append(f"Quantity: {qty}")
    lines.append(f"Price: {unit} each → {line_total}")
    base = _frontend_base()
    if base:
        lines.append(f"Link: {base}/p/{product.short_id}")
    return "\n".join(lines)


def build_cart_summary(cart: Any, *, context: str) -> str:
    totals = compute_cart_totals(cart)
    header = "🛒 *Order inquiry*" if context == "cart" else "🧾 *Checkout inquiry*"
    lines = [f"{header} — {_store_name()}", ""]
    for i, ln in enumerate(totals["lines"], start=1):
        unit = ln["unit_price"]["formatted"]
        total = ln["line_total"]["formatted"]
        lines.append(f"{i}. {ln['product_title']} ×{ln['quantity']} — {total} ({unit} ea)")
    lines.append("")
    lines.append(f"Total: {totals['total']['formatted']}")
    return "\n".join(lines)


def _contact_block(name: str, phone: str, note: str) -> str:
    extra = []
    if name:
        extra.append(f"Customer: {name}")
    if phone:
        extra.append(f"Phone: {phone}")
    if note:
        extra.append(f"Note: {note}")
    return ("\n\n" + "\n".join(extra)) if extra else ""


def create_inquiry(
    *,
    channel: str,
    context: str,
    variant: Variant | None = None,
    quantity: int = 1,
    cart: Any = None,
    customer_name: str = "",
    customer_phone: str = "",
    note: str = "",
    user: Any = None,
) -> tuple[OrderInquiry, str]:
    """Build the message, persist the inquiry, push to ops Telegram if possible."""
    if context == "product" and variant is not None:
        body = build_product_summary(variant, quantity)
    elif cart is not None:
        body = build_cart_summary(cart, context=context)
    else:
        body = f"🛍️ *Order inquiry* — {_store_name()}"

    summary = body + _contact_block(customer_name, customer_phone, note)

    inquiry = OrderInquiry.objects.create(
        channel=channel,
        context=context,
        user=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
        customer_name=customer_name,
        customer_phone=customer_phone,
        note=note,
        summary=summary,
    )

    # Real-time push to store ops (Telegram), best-effort.
    ops = str(getattr(settings, "TELEGRAM_DEFAULT_CHAT_ID", "") or "")
    if ops:
        try:
            from apps.notifications import events
            from apps.notifications.services import dispatch

            dispatch(
                events.ORDER_INQUIRY,
                context={"message": summary},
                dedupe_key=f"order_inquiry:{inquiry.id}",
                telegram_chat_id=ops,
            )
            inquiry.delivered_to_ops = True
            inquiry.save(update_fields=["delivered_to_ops"])
        except Exception:  # noqa: BLE001 - never break the user's click
            pass

    return inquiry, summary


def channel_links(summary: str) -> dict[str, str]:
    """Deep links for each configured channel (with prefilled text where supported)."""
    text = quote(summary)
    tg_url = _cfg("order_chat.telegram_url").strip()
    wa_number = "".join(ch for ch in _cfg("order_chat.whatsapp_number") if ch.isdigit())
    phone = _cfg("order_chat.phone_number").strip()

    telegram = ""
    if tg_url:
        sep = "&" if "?" in tg_url else "?"
        telegram = f"{tg_url}{sep}text={text}"
    whatsapp = f"https://wa.me/{wa_number}?text={text}" if wa_number else ""
    call = f"tel:{phone}" if phone else ""
    return {"telegram": telegram, "whatsapp": whatsapp, "call": call}
