"""Hermetic settings for the test suite.

No external services required: SQLite, in-memory cache, eager Celery, and a
locmem email backend. Keeps `pytest` runnable anywhere (CI or laptop) without a
Postgres/Redis container.
"""

from __future__ import annotations

from .dev import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Deterministic key of adequate length so JWT signing doesn't warn in tests.
SECRET_KEY = "test-secret-key-long-enough-for-hmac-sha256-signing-000000"

# Never touch the real Cloudinary account from tests.
CATALOG_IMAGE_BACKEND = "mock"

# In-memory notification channels — never hit ZeptoMail/Telegram from tests.
NOTIFICATIONS_EMAIL_BACKEND = "memory"
NOTIFICATIONS_TELEGRAM_BACKEND = "memory"
TELEGRAM_DEFAULT_CHAT_ID = "ops-chat"
