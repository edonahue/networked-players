# Networked Players — canonical command surface.
#
# Thin wrappers over the existing `uv` commands so humans and AI coding agents
# (Claude, Codex) share one discoverable entry point. No hidden behavior: every
# target maps to a command documented in README.md / AGENTS.md.

.DEFAULT_GOAL := help
.PHONY: help setup test lint fmt fmt-check typecheck check ingest ingest-check ingest-recovery-check profile-discogs expand-onehop \
	backup-coordination restore-coordination backup-swarm-manager restore-swarm-manager \
	cluster-health cluster-benchmark cluster-onboard cluster-swarm-join cluster-smoke-test \
	cluster-recovery-drill harden-workers equip-workers equip-x86-workers deploy-jobs-broker deploy-catalog-data cluster-benchmark-distributed \
	dask-up dask-down

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

ingest-recovery-check: ## Report valid vs. corrupt parts in an interrupted/in-progress ingest (needs SNAPSHOT=YYYYMMDD)
	./scripts/check-ingest-recovery.sh

profile-discogs: ## Profile a completed Discogs dataset with DuckDB (needs SNAPSHOT=YYYYMMDD)
	./scripts/profile-discogs-dataset.sh

expand-onehop: ## One-hop expansion from the private seed over a parsed snapshot (Milestone 5; needs SNAPSHOT=YYYYMMDD)
	@test -n "$(SNAPSHOT)" || (echo "Set SNAPSHOT=YYYYMMDD (a completed parse under local/processed/discogs/)" >&2; exit 1)
	uv run networked-players-catalog expand-one-hop \
		--dataset local/processed/discogs/snapshot=$(SNAPSHOT) \
		--output-root local/processed/discogs-onehop $(ARGS)

backup-coordination: ## Back up the Postgres/Redis dev-loop stack (pg_dump + Redis BGSAVE, no downtime)
	./scripts/backup-coordination-stack.sh

restore-coordination: ## Restore the Postgres/Redis stack (needs BACKUP_DIR=local/backups/coordination/<ts>)
	./scripts/restore-coordination-stack.sh "$(BACKUP_DIR)"

backup-swarm-manager: ## Back up Swarm manager CA/raft state (sudo, brief Docker downtime)
	./scripts/backup-swarm-manager-state.sh

restore-swarm-manager: ## Restore Swarm manager state (needs BACKUP_FILE=...swarm-state.tar.gz; DESTRUCTIVE)
	./scripts/restore-swarm-manager-state.sh "$(BACKUP_FILE)" --yes-i-am-sure

cluster-health: ## Confirm every inventory node is reachable and healthy (read-only); ARGS="--limit workers"
	./infra/ansible/run-health-local.sh $(ARGS)

cluster-benchmark: ## Benchmark CPU/memory per node type; run cluster-health first; ARGS="--limit workers"
	./infra/ansible/run-benchmark-local.sh $(ARGS)

cluster-onboard: ## Install Docker + docker-group on fleet nodes (ADR 0015); ARGS="--limit workers --ask-become-pass"
	./infra/ansible/run-onboard-local.sh $(ARGS)

cluster-swarm-join: ## Guarded, one-worker-at-a-time Swarm join (ADR 0017); needs CONFIRM=yes ARGS="--limit worker-01 --ask-become-pass"
	@test "$(CONFIRM)" = "yes" || (echo "Set CONFIRM=yes to run the guarded Swarm join (see infra/swarm/README.md)" >&2; exit 1)
	./infra/ansible/run-swarm-join-local.sh -e confirm_swarm_join=true $(ARGS)

cluster-smoke-test: ## Deploy + verify + remove a harmless worker-only smoke service
	./infra/swarm/run-worker-smoke-test.sh

cluster-recovery-drill: ## Destructive one-worker drain/remove drill; needs ARGS="--yes-i-am-sure --worker worker-01"
	./infra/swarm/run-worker-recovery-drill.sh $(ARGS)

harden-workers: ## Arm watchdog + Docker log rotation on Pi 3B workers; ARGS="--ask-become-pass"
	./infra/ansible/run-harden-workers-local.sh $(ARGS)

equip-workers: ## Install baseline tooling (uv, duckdb, jq, redis-tools, worker venv) on Pi 3B workers; ARGS="--ask-become-pass"
	./infra/ansible/run-equip-workers-local.sh $(ARGS)

equip-x86-workers: ## Install baseline RQ/Dask tooling (uv, duckdb, worker venv, no apt) on x86_64 Swarm workers (ADR 0023); ARGS="--limit x86-worker-01 --ask-become-pass"
	./infra/ansible/run-equip-x86-workers-local.sh $(ARGS)

deploy-jobs-broker: ## Start the LAN-reachable jobs-broker Redis for cluster benchmarking (ADR 0019); "make deploy-jobs-broker ARGS=--down" to stop
	./infra/swarm/deploy-jobs-broker.sh $(ARGS)

deploy-catalog-data: ## Serve local/processed read-only over LAN HTTP for remote workers (ADR 0024); "make deploy-catalog-data ARGS=--down" to stop
	./infra/swarm/deploy-catalog-data.sh $(ARGS)

cluster-benchmark-distributed: ## Cluster-vs-single-node RQ benchmark; needs deploy-jobs-broker + joined workers; writes local/benchmarks/ only
	./scripts/cluster-benchmark-distributed.sh $(ARGS)

dask-up: ## Build the image, start Jupyter, and deploy the Dask scheduler/worker Swarm stack (see infra/dask/README.md)
	./infra/dask/deploy-dask.sh

dask-down: ## Stop Jupyter and remove the Dask Swarm stack
	./infra/dask/deploy-dask.sh --down
