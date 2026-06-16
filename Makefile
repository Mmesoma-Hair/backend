# IdealCommerce backend — common commands.
#
# Packages are managed with `uv` (https://docs.astral.sh/uv/). `uv run` executes
# inside the project environment described by pyproject.toml + uv.lock, syncing
# it on demand, so there's no separate "activate the venv" step.
#
# Quick local runs without Postgres/Redis use SQLite + inline Celery; override by
# exporting USE_SQLITE=0 and pointing POSTGRES_*/REDIS_URL at real services.

UV ?= uv
RUN := $(UV) run
MANAGE := $(RUN) python manage.py

# Sensible defaults for `make run`/`make migrate` on a laptop with no services.
export USE_SQLITE ?= 1
export DJANGO_SECRET_KEY ?= local-dev-secret-key-change-me
export DJANGO_SETTINGS_MODULE ?= config.settings.dev

.DEFAULT_GOAL := help
.PHONY: help install lock sync run worker beat shell migrate makemigrations \
        check superuser test test-cov lint format typecheck schema clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: sync ## Alias for `sync`

lock: ## Update uv.lock from pyproject.toml
	$(UV) lock

sync: ## Install/refresh the environment (incl. dev tools) from uv.lock
	$(UV) sync

run: ## Run the dev server (http://localhost:8000)
	$(MANAGE) runserver 0.0.0.0:8000

worker: ## Run a Celery worker
	$(RUN) celery -A config worker -l info

beat: ## Run Celery Beat (scheduled tasks)
	$(RUN) celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

shell: ## Open the Django shell
	$(MANAGE) shell

migrate: ## Apply database migrations
	$(MANAGE) migrate

makemigrations: ## Create new migrations from model changes
	$(MANAGE) makemigrations

check: ## Run Django system checks + migration drift check
	$(MANAGE) check
	$(MANAGE) makemigrations --check --dry-run

superuser: ## Create a superuser (admin role)
	$(MANAGE) createsuperuser

seed: ## Seed demo data (currencies + rates, catalog, coupons)
	$(MANAGE) seed_currencies
	$(MANAGE) seed_catalog
	$(MANAGE) seed_coupons

test: ## Run the test suite
	$(RUN) pytest

test-cov: ## Run tests with coverage
	$(RUN) pytest --cov=apps --cov-report=term-missing

lint: ## Lint with ruff + check formatting with black
	$(RUN) ruff check .
	$(RUN) black --check .

format: ## Auto-fix lint issues and format the code
	$(RUN) ruff check --fix .
	$(RUN) black .

typecheck: ## Static type-check with mypy
	$(RUN) mypy .

schema: ## Generate the OpenAPI schema to schema.yml
	$(MANAGE) spectacular --file schema.yml

clean: ## Remove caches and the local SQLite database
	rm -rf .pytest_cache .ruff_cache .mypy_cache db.sqlite3
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
