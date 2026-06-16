"""Development settings."""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import REST_FRAMEWORK, env_bool

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Console email in dev (notifications module uses this in later phases).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Make exploring the API friction-free locally.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
}

# Run Celery tasks inline unless a worker is explicitly wired up.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)
