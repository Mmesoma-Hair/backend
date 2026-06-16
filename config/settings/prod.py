"""Production settings.

All sensitive values must come from the environment; this module only tightens
security defaults and fails loudly if the secret key was left at its dev value.
"""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import SECRET_KEY, env_bool

DEBUG = False

if SECRET_KEY == "insecure-dev-key-change-me":
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production.")

# Security hardening.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True

# Real workers in prod; never run tasks eagerly.
CELERY_TASK_ALWAYS_EAGER = False
