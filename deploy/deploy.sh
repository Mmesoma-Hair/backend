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

# Pull from git when a remote is reachable (deploy-key setups); otherwise assume
# the code was already delivered to disk (the scp-based CI workflow does this).
if git rev-parse --git-dir >/dev/null 2>&1 && git ls-remote origin >/dev/null 2>&1; then
  echo "==> Fetching latest code (origin/main)"
  git fetch --all --prune
  git reset --hard origin/main
else
  echo "==> No reachable git remote; using code already on disk"
fi

echo "==> Installing dependencies (frozen, no dev)"
uv sync --frozen --no-dev

echo "==> Applying database migrations"
.venv/bin/python manage.py migrate --noinput

echo "==> Collecting static files"
.venv/bin/python manage.py collectstatic --noinput

# Bust the settings/FX cache so newly-deployed storeconfig specs surface
# immediately (the settings map is cached with no expiry).
echo "==> Clearing caches"
.venv/bin/python manage.py shell -c "from django.core.cache import cache; cache.clear()" || true

echo "==> Restarting services"
sudo systemctl restart gunicorn celery-worker celery-beat

echo "==> Deploy complete:"
sudo systemctl is-active gunicorn celery-worker celery-beat
