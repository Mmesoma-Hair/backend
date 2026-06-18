#!/usr/bin/env bash
#
# IdealCommerce API deploy — pulls latest main, installs deps, migrates,
# collects static and restarts services. Safe to run repeatedly (idempotent).
# Runs as the `prime` user; restarting services uses passwordless sudo limited
# to the three unit files (see deploy/sudoers.d-prime).
#
set -euo pipefail

APP_DIR="${APP_DIR:-/home/prime/nasuru-api}"
export PATH="$HOME/.local/bin:$PATH"
export DJANGO_SETTINGS_MODULE=config.settings.prod

cd "$APP_DIR"

echo "==> Fetching latest code (origin/main)"
git fetch --all --prune
git reset --hard origin/main

echo "==> Installing dependencies (frozen, no dev)"
uv sync --frozen --no-dev

echo "==> Applying database migrations"
.venv/bin/python manage.py migrate --noinput

echo "==> Collecting static files"
.venv/bin/python manage.py collectstatic --noinput

echo "==> Restarting services"
sudo systemctl restart gunicorn celery-worker celery-beat

echo "==> Deploy complete:"
sudo systemctl is-active gunicorn celery-worker celery-beat
