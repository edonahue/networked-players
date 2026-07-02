# Networked Players — canonical command surface.
#
# Thin wrappers over the existing `uv` commands so humans and AI coding agents
# (Claude, Codex) share one discoverable entry point. No hidden behavior: every
# target maps to a command documented in README.md / AGENTS.md.

.DEFAULT_GOAL := help
.PHONY: help setup test lint fmt fmt-check typecheck check ingest ingest-check profile-discogs

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python deps with dev extras (uv sync --extra dev)
	uv sync --extra dev

test: ## Run the test suite
	uv run pytest

lint: ## Lint with Ruff
	uv run ruff check .

fmt: ## Format with Ruff
	uv run ruff format .

fmt-check: ## Check formatting without writing
	uv run ruff format --check .

typecheck: ## Type-check with mypy
	uv run mypy

check: lint fmt-check typecheck test ## Run every gate CI runs (lint + format + types + tests)

ingest: ## Run a Discogs ingestion slice (see scripts/run-ingest.sh and docs/OPERATOR_SETUP.md)
	./scripts/run-ingest.sh

ingest-check: ## Check disk-space feasibility for a bounded Discogs ingest slice
	./scripts/check-ingest-feasibility.sh

profile-discogs: ## Profile a completed Discogs dataset with DuckDB (needs SNAPSHOT=YYYYMMDD)
	./scripts/profile-discogs-dataset.sh
