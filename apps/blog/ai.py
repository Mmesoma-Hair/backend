"""AI blog writer via OpenRouter.

The API key + model are admin-configurable (storeconfig ``blog.openrouter_api_key``
/ ``blog.ai_model``) with env fallbacks. The model is asked to return a JSON
object so we can populate the post's title, excerpt, meta description, tags and
Markdown body in one call.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests
from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError

from apps.storeconfig import selectors as config_selectors

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
_TIMEOUT = 90

SYSTEM_PROMPT = (
    "You are an expert SEO copywriter for an online clothing & fashion store based "
    "in Lagos, Nigeria. Write engaging, original, genuinely useful blog posts in "
    "Markdown that are structured to rank on Google. Use a compelling intro, clear "
    "## and ### headings, short scannable paragraphs, and bullet lists where helpful. "
    "Weave the target keywords in naturally (no stuffing). Never invent fake facts, "
    "prices, statistics or testimonials. "
    "Respond with ONLY a single JSON object with these keys: "
    '"title" (string), "excerpt" (1-2 sentence summary), "meta_description" '
    '(<=155 chars, SEO), "tags" (array of 3-6 short lowercase strings), and '
    '"body" (the article in Markdown, ~700-1100 words, do NOT include an H1).'
)


class AiUnavailable(APIException):
    status_code = 503
    default_detail = "The AI writer is unavailable right now. Please try again."
    default_code = "ai_unavailable"


def _cfg(key: str, default: str = "") -> str:
    try:
        return str(config_selectors.get_setting(key, default) or default)
    except Exception:  # noqa: BLE001 - config lookup must never hard-fail
        return default


def _api_key() -> str:
    return (_cfg("blog.openrouter_api_key") or getattr(settings, "OPENROUTER_API_KEY", "")).strip()


def _model() -> str:
    return (
        _cfg("blog.ai_model") or getattr(settings, "OPENROUTER_MODEL", "") or DEFAULT_MODEL
    ).strip()


def generate_blog(*, topic: str, tone: str = "", keywords: str = "") -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise ValidationError(
            {"detail": "Add your OpenRouter API key in Settings before using the AI writer."}
        )

    user = f"Topic / working title: {topic}\n"
    if tone:
        user += f"Tone of voice: {tone}\n"
    if keywords:
        user += f"Target keywords to include: {keywords}\n"
    user += "Write the complete blog post now as the JSON object described."

    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": str(getattr(settings, "API_PUBLIC_BASE_URL", "") or ""),
        "X-Title": "Storefront Blog",
    }

    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise AiUnavailable(f"Could not reach the AI provider: {exc}") from exc
    if resp.status_code >= 400:
        raise AiUnavailable(f"AI provider error {resp.status_code}: {resp.text[:300]}")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise AiUnavailable("Unexpected response from the AI provider.") from exc

    return _parse(content, topic)


def _parse(content: str, topic: str) -> dict[str, Any]:
    data: Any = None
    try:
        data = json.loads(content)
    except ValueError:
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except ValueError:
                data = None

    if not isinstance(data, dict):
        # Model didn't return JSON — use the whole text as the body.
        return {
            "title": topic,
            "excerpt": "",
            "meta_description": "",
            "tags": [],
            "body": content.strip(),
        }

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    tags = [str(t).strip() for t in tags if str(t).strip()][:6]

    return {
        "title": str(data.get("title") or topic).strip(),
        "excerpt": str(data.get("excerpt") or "").strip(),
        "meta_description": str(data.get("meta_description") or "").strip(),
        "tags": tags,
        "body": str(data.get("body") or "").strip(),
    }
