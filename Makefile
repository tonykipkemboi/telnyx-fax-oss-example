SHELL := /bin/bash

UV ?= uv
HOST ?= 0.0.0.0
PORT ?= 8000
MESSAGE ?= migration

.DEFAULT_GOAL := help

.PHONY: help env sync dev run run-prod test test-cov lint format fix check migrate-up migrate-down migrate-new clean

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; print "Usage: make <target>\n\nTargets:"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Create .env from .env.example if missing
	@if [ ! -f .env ] && [ -f .env.example ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example"; \
	elif [ -f .env ]; then \
		echo ".env already exists"; \
	else \
		echo "No .env.example found; create .env manually"; \
	fi

sync: ## Install/update dependencies via uv (dev extras included)
	$(UV) sync --extra dev

run: ## Run FastAPI app (stable mode, no auto-reload)
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)

run-prod: ## Run app with workers (prod-like local run)
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT) --workers 2

dev: sync env ## Sync deps and run app with auto-reload
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT) --reload --reload-exclude ".venv/*" --reload-exclude ".git/*" --reload-exclude "*.db"

test: ## Run test suite
	$(UV) run pytest

test-cov: ## Run tests with coverage
	$(UV) run pytest --cov=app --cov-report=term-missing

lint: ## Run Ruff lint checks
	$(UV) run ruff check .

format: ## Format code with Ruff
	$(UV) run ruff format .

fix: ## Auto-fix lint issues and format
	$(UV) run ruff check . --fix
	$(UV) run ruff format .

check: lint test ## Run lint and tests

migrate-up: ## Apply Alembic migrations
	$(UV) run alembic upgrade head

migrate-down: ## Roll back one Alembic migration
	$(UV) run alembic downgrade -1

migrate-new: ## Create new Alembic migration (usage: make migrate-new MESSAGE="add column")
	$(UV) run alembic revision -m "$(MESSAGE)"

clean: ## Remove caches and test artifacts
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
