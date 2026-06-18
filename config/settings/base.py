"""Base Django settings shared across environments.

Environment-specific overrides live in ``dev.py`` and ``prod.py``. Nothing here
should hardcode a secret — every sensitive or deployment-specific value is read
from the environment via :func:`env`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# backend/config/settings/base.py -> backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load a .env file if present (no-op in production where env is injected).
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(key)
    if not raw:
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

# --- Applications -----------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "django_celery_beat",
    "cloudinary",
    "cloudinary_storage",
]

# Local domain apps. Phase 1 ships common + storeconfig; later phases append.
LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.storeconfig",
    "apps.catalog",
    "apps.inventory",
    "apps.currency",
    "apps.promotions",
    "apps.cart",
    "apps.orders",
    "apps.payments",
    "apps.suppliers",
    "apps.fulfillment",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------
# Postgres is the real backend. USE_SQLITE=1 swaps in SQLite for quick local
# runs / sanity checks that don't need a Postgres server (never in prod).
if env_bool("USE_SQLITE", False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "idealcommerce"),
            "USER": env("POSTGRES_USER", "idealcommerce"),
            "PASSWORD": env("POSTGRES_PASSWORD", "idealcommerce"),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
        }
    }

# --- Auth -------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
AUTH_USER_MODEL = "accounts.User"

# --- i18n / tz --------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static / media ---------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF --------------------------------------------------------------------
REST_FRAMEWORK: dict[str, Any] = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "IdealCommerce API",
    "DESCRIPTION": "Modular e-commerce + dropshipping platform.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

# --- JWT (SimpleJWT) --------------------------------------------------------
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_ACCESS_MINUTES", "15") or "15")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env("JWT_REFRESH_DAYS", "7") or "7")),
    # Refresh-token rotation: each refresh issues a new refresh token and
    # blacklists the old one so a leaked refresh token has a short useful life.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "TOKEN_OBTAIN_SERIALIZER": "apps.accounts.serializers.TokenObtainPairSerializer",
}

# Frontend base URL used to build password-reset links in emails.
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", "http://localhost:3000")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "no-reply@idealcommerce.test")

# --- Celery -----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", env("REDIS_URL", "redis://localhost:6379/0"))
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", env("REDIS_URL", "redis://localhost:6379/0"))
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Periodic tasks. The FX refresh cadence is admin-tunable (storeconfig
# `currency.refresh_minutes`); this is the default schedule the worker starts with.
CELERY_BEAT_SCHEDULE = {
    "refresh-exchange-rates": {
        "task": "apps.currency.tasks.refresh_exchange_rates",
        "schedule": float(env("CURRENCY_REFRESH_SECONDS", "3600") or "3600"),
    },
    "release-expired-reservations": {
        "task": "apps.inventory.tasks.release_expired_reservations",
        "schedule": 300.0,
    },
    "poll-supplier-orders": {
        "task": "apps.fulfillment.tasks.poll_supplier_orders",
        "schedule": 600.0,
    },
    "sync-suppliers": {
        "task": "apps.suppliers.tasks.sync_all_suppliers",
        "schedule": 3600.0,
    },
}

# --- Cache ------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", "redis://localhost:6379/1"),
        # Fail fast if Redis is unreachable so callers can fall back to the DB
        # (selectors swallow cache errors) instead of blocking on retries.
        "OPTIONS": {"socket_connect_timeout": 1, "socket_timeout": 1},
    }
}

# --- Cloudinary -------------------------------------------------------------
# Either CLOUDINARY_URL or the discrete cloud-name/key/secret trio.
CLOUDINARY_STORAGE = {
    "CLOUD_NAME": env("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": env("CLOUDINARY_API_KEY"),
    "API_SECRET": env("CLOUDINARY_API_SECRET"),
}
CLOUDINARY_CLOUD_NAME = env("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = env("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = env("CLOUDINARY_API_SECRET")
CLOUDINARY_UPLOAD_FOLDER = env("CLOUDINARY_UPLOAD_FOLDER", "idealcommerce/products")

# Pluggable product-image backend. "cloudinary" hits the real account; "static"
# serves generated SVGs from the storefront's /public folder (key-less local dev
# / demos); "mock" keeps tests off the network. Defaults to cloudinary when a
# cloud name is configured, otherwise the static demo images.
CATALOG_IMAGE_BACKEND = env(
    "CATALOG_IMAGE_BACKEND",
    "cloudinary" if env("CLOUDINARY_CLOUD_NAME") else "static",
)
# Origin the storefront serves generated product SVGs from. Empty = root-relative
# (same origin as the storefront), which is what the demo uses.
STATIC_IMAGE_BASE_URL = env("STATIC_IMAGE_BASE_URL", "")
# Where `generate_product_images` writes the SVGs (the storefront's public dir).
PRODUCT_IMAGE_OUTPUT_DIR = env(
    "PRODUCT_IMAGE_OUTPUT_DIR",
    str(BASE_DIR.parent / "frontend" / "public" / "products"),
)

# --- CORS -------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", ["http://localhost:3000"])
CORS_ALLOW_CREDENTIALS = True

# --- App-specific defaults --------------------------------------------------
# FX rates provider (currency module, wired up in Phase 4).
RATES_PROVIDER = env("RATES_PROVIDER", "mock")
CURRENCY_API_NET_KEY = env("CURRENCY_API_NET_KEY")

# Payments. Provider-agnostic: "mock" | "paystack" | "flutterwave".
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", "mock")
PAYMENT_WEBHOOK_SECRET = env("PAYMENT_WEBHOOK_SECRET", "dev-webhook-secret")
PAYMENT_HTTP_TIMEOUT = int(env("PAYMENT_HTTP_TIMEOUT", "15") or "15")
# Public base URL of THIS API (used to show the webhook URL admins paste into
# the gateway dashboard). In prod set to your real domain; for local testing
# with Paystack/Flutterwave use your tunnel URL (e.g. an ngrok https URL).
API_PUBLIC_BASE_URL = env("API_PUBLIC_BASE_URL", "http://localhost:8000")
# Where the gateway redirects the shopper after paying. {order} is the order
# number; the gateway appends its own params (reference/tx_ref/status).
PAYMENT_RETURN_URL = env(
    "PAYMENT_RETURN_URL",
    f"{FRONTEND_BASE_URL.rstrip('/')}/checkout/processing?order={{order}}",
)
# Paystack (https://dashboard.paystack.com)
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = env("PAYSTACK_PUBLIC_KEY", "")
# Flutterwave (https://dashboard.flutterwave.com). SECRET_HASH must match the
# value set in the dashboard webhook settings (sent as the verif-hash header).
FLUTTERWAVE_SECRET_KEY = env("FLUTTERWAVE_SECRET_KEY", "")
FLUTTERWAVE_PUBLIC_KEY = env("FLUTTERWAVE_PUBLIC_KEY", "")
FLUTTERWAVE_SECRET_HASH = env("FLUTTERWAVE_SECRET_HASH", "")

# --- Notifications (Phase 9) ------------------------------------------------
# Provider-agnostic transactional dispatch. Email + Telegram, async via Celery.
# Email backend: console | zeptomail | django | memory
NOTIFICATIONS_EMAIL_BACKEND = env("NOTIFICATIONS_EMAIL_BACKEND", "console")
# Telegram backend: console | http | memory | disabled
NOTIFICATIONS_TELEGRAM_BACKEND = env("NOTIFICATIONS_TELEGRAM_BACKEND", "console")
NOTIFICATIONS_HTTP_TIMEOUT = int(env("NOTIFICATIONS_HTTP_TIMEOUT", "10") or "10")

# ZeptoMail (Zoho) HTTP email API. Secrets come from the environment only.
ZEPTOMAIL_API_URL = env("ZEPTOMAIL_API_URL", "https://api.zeptomail.com/v1.1/email")
ZEPTOMAIL_TOKEN = env("ZEPTOMAIL_TOKEN", "")

# Sender identity + branding used in emails.
EMAIL_FROM_ADDRESS = env(
    "EMAIL_FROM_ADDRESS", env("DEFAULT_FROM_EMAIL", "no-reply@idealcommerce.test")
)
EMAIL_FROM_NAME = env("EMAIL_FROM_NAME", "IdealCommerce")
SUPPORT_EMAIL = env("SUPPORT_EMAIL", "support@idealcommerce.test")
EMAIL_LOGO_URL = env("EMAIL_LOGO_URL", f"{FRONTEND_BASE_URL.rstrip('/')}/logo.png")

# Telegram bot. TELEGRAM_DEFAULT_CHAT_ID is the store-ops chat (new-order alerts).
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_DEFAULT_CHAT_ID = env("TELEGRAM_DEFAULT_CHAT_ID", "")
