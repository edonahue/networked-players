# Networked Players — canonical command surface.
#
# Thin wrappers over the existing `uv` commands so humans and AI coding agents
# (Claude, Codex) share one discoverable entry point. No hidden behavior: every
# target maps to a command documented in README.md / AGENTS.md.

.DEFAULT_GOAL := help
.PHONY: help setup test lint fmt fmt-check typecheck validate-public-artifacts validate-album-catalog-audit check ingest ingest-check ingest-recovery-check profile-discogs expand-onehop build-challenge export-graph-snapshot \
	backup-coordination restore-coordination backup-swarm-manager restore-swarm-manager \
	cluster-health cluster-benchmark cluster-onboard cluster-swarm-join cluster-smoke-test \
	cluster-recovery-drill harden-workers equip-workers equip-x86-workers replicate-x86 replicate-pi deploy-jobs-broker deploy-catalog-data cluster-benchmark-distributed \
	deploy-verify-job verify-challenge-distributed \
	deploy-connection-rounds-check-job connection-rounds-check-distributed \
	deploy-record-routes-check-job record-routes-check-distributed \
	deploy-daily-manifest-check-job daily-manifest-check-distributed \
	deploy-album-art-check-job album-art-check-distributed \
	deploy-catalog-check-job catalog-check-distributed \
	score-cohort-on-worker \
	platform-build platform-deploy platform-status curator \
	dask-up dask-down

help: ## List available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python deps with dev + jobs extras (uv sync --extra dev --extra jobs)
	uv sync --extra dev --extra jobs

test: ## Run the test suite (needs the jobs extra -- see setup)
	uv run pytest

lint: ## Lint with Ruff
	uv run ruff check .

fmt: ## Format with Ruff
	uv run ruff format .

fmt-check: ## Check formatting without writing
	uv run ruff format --check .

typecheck: ## Type-check with mypy
	uv run mypy

validate-public-artifacts: ## Validate the real committed public artifacts (catalog, art registry, both game modes, daily manifest, challenge) against their contracts
	uv run networked-players-catalog validate-public-artifacts

validate-album-catalog-audit: ## Validate the committed studio-album inclusion audit against the catalog (docs/data/, not a public web artifact -- separate from validate-public-artifacts)
	uv run networked-players-catalog validate-album-catalog-audit

check: lint fmt-check typecheck test validate-public-artifacts validate-album-catalog-audit ## Run every gate CI runs (lint + format + types + tests + public-artifact validation + catalog-audit validation)

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

build-challenge: ## Build the album-centered challenge.v2 artifact from a one-hop dataset (needs SNAPSHOT=YYYYMMDD)
	@test -n "$(SNAPSHOT)" || (echo "Set SNAPSHOT=YYYYMMDD (a completed expand-onehop under local/processed/discogs-onehop/)" >&2; exit 1)
	uv run networked-players-catalog build-challenge-from-dump \
		--onehop-root local/processed/discogs-onehop/snapshot=$(SNAPSHOT) \
		--albums data/albums/top-albums-v1.json \
		--output apps/web/public/data/challenge.v2.json $(ARGS)

export-graph-snapshot: ## Export the materialized co-credit graph snapshot from a one-hop dataset (needs SNAPSHOT=YYYYMMDD)
	@test -n "$(SNAPSHOT)" || (echo "Set SNAPSHOT=YYYYMMDD (a completed expand-onehop under local/processed/discogs-onehop/)" >&2; exit 1)
	uv run networked-players-catalog export-graph-snapshot \
		--dataset local/processed/discogs-onehop/snapshot=$(SNAPSHOT) \
		--output-root local/processed/discogs-graph $(ARGS)

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

replicate-x86: ## Replicate a dataset into an x86 worker's local cache (ADR 0025); needs DATASET=, SNAPSHOT=; CATALOG_DATA_URL= unless ARGS contains -e verify_only=true
	@test -n "$(DATASET)" || (echo "Set DATASET=discogs|discogs-onehop|discogs-masters" >&2; exit 1)
	@test -n "$(SNAPSHOT)" || (echo "Set SNAPSHOT=YYYYMMDD" >&2; exit 1)
	./infra/ansible/run-replicate-dataset-x86-local.sh \
		-e dataset=$(DATASET) -e snapshot=$(SNAPSHOT) $(if $(CATALOG_DATA_URL),-e catalog_data_url=$(CATALOG_DATA_URL)) $(ARGS)

replicate-pi: ## Replicate the one-hop dataset into a Pi worker's bounded cache (ADR 0025); needs SNAPSHOT=; CATALOG_DATA_URL= unless ARGS contains -e verify_only=true; ARGS="--limit worker-01"
	@test -n "$(SNAPSHOT)" || (echo "Set SNAPSHOT=YYYYMMDD" >&2; exit 1)
	./infra/ansible/run-replicate-dataset-pi-local.sh \
		-e snapshot=$(SNAPSHOT) $(if $(CATALOG_DATA_URL),-e catalog_data_url=$(CATALOG_DATA_URL)) $(ARGS)

deploy-jobs-broker: ## Start the LAN-reachable jobs-broker Redis for cluster benchmarking (ADR 0019); "make deploy-jobs-broker ARGS=--down" to stop
	./infra/swarm/deploy-jobs-broker.sh $(ARGS)

deploy-catalog-data: ## Serve local/processed read-only over LAN HTTP for remote workers (ADR 0024); "make deploy-catalog-data ARGS=--down" to stop
	./infra/swarm/deploy-catalog-data.sh $(ARGS)

cluster-benchmark-distributed: ## Cluster-vs-single-node RQ benchmark; needs deploy-jobs-broker + joined workers; writes local/benchmarks/ only
	./scripts/cluster-benchmark-distributed.sh $(ARGS)

deploy-verify-job: ## Deploy the challenge-evidence verification job to Pi workers; ARGS="--limit worker-01"
	./infra/ansible/run-deploy-verify-job-local.sh $(ARGS)

verify-challenge-distributed: ## Re-verify a challenge.v2 artifact's evidence across Pi workers' local caches (ADR 0025); needs deploy-jobs-broker + deploy-verify-job; writes local/jobs/ only
	./scripts/enqueue-verify-challenge.sh $(ARGS)

deploy-connection-rounds-check-job: ## Deploy the Connection Guesser rounds-pool validation job + connection-universe.v1/connection-rounds.v1 artifacts to Pi workers; ARGS="--limit worker-01"
	./infra/ansible/run-deploy-connection-rounds-check-job-local.sh $(ARGS)

connection-rounds-check-distributed: ## Independently re-validate the published Connection Guesser rounds pool on every Pi worker (one job per worker, pass only if all pass); needs deploy-jobs-broker + deploy-connection-rounds-check-job; writes local/jobs/ only; ARGS="--limit worker-01" to debug one worker
	./scripts/enqueue-connection-rounds-check.sh $(ARGS)

deploy-record-routes-check-job: ## Deploy the Record Routes validation job + routes-universe.v1/routes-rounds.v1 artifacts to Pi workers; ARGS="--limit worker-01"
	./infra/ansible/run-deploy-record-routes-check-job-local.sh $(ARGS)

record-routes-check-distributed: ## Independently re-validate the published Record Routes pool on every Pi worker (one job per worker, pass only if all pass); needs deploy-jobs-broker + deploy-record-routes-check-job; writes local/jobs/ only; ARGS="--limit worker-01" to debug one worker
	./scripts/enqueue-record-routes-check.sh $(ARGS)

deploy-daily-manifest-check-job: ## Deploy the Connection-daily-manifest validation job + daily-manifest.v1/connection-rounds.v1 artifacts to Pi workers; ARGS="--limit worker-01"
	./infra/ansible/run-deploy-daily-manifest-check-job-local.sh $(ARGS)

daily-manifest-check-distributed: ## Independently re-validate the published daily manifest on every Pi worker (one job per worker, pass only if all pass); needs deploy-jobs-broker + deploy-daily-manifest-check-job; writes local/jobs/ only; ARGS="--limit worker-01" to debug one worker
	./scripts/enqueue-daily-manifest-check.sh $(ARGS)

deploy-album-art-check-job: ## Deploy the album-art-registry validation job + album-art.v1/albums.v1 artifacts to Pi workers; ARGS="--limit worker-01"
	./infra/ansible/run-deploy-album-art-check-job-local.sh $(ARGS)

album-art-check-distributed: ## Independently re-validate the published album-art registry on every Pi worker (one job per worker, pass only if all pass); needs deploy-jobs-broker + deploy-album-art-check-job; writes local/jobs/ only; ARGS="--limit worker-01" to debug one worker
	./scripts/enqueue-album-art-check.sh $(ARGS)

deploy-catalog-check-job: ## Deploy the public-album-catalog validation job + albums.v1 artifact to Pi workers; ARGS="--limit worker-01"
	./infra/ansible/run-deploy-catalog-check-job-local.sh $(ARGS)

catalog-check-distributed: ## Independently re-validate the published public album catalog on every Pi worker (one job per worker, pass only if all pass); needs deploy-jobs-broker + deploy-catalog-check-job; writes local/jobs/ only; ARGS="--limit worker-01" to debug one worker
	./scripts/enqueue-catalog-check.sh $(ARGS)

score-cohort-on-worker: ## Submit whole-cohort scoring to a matching platform worker; needs platform runtime + verified x86 cache; ARGS="--source-id <id> --snapshot-date <date> [--release-format-policy <path>]"
	./scripts/score-cohort-on-worker.sh $(ARGS)

platform-build: ## Build immutable contracts/platform wheels under local/platform/releases/<commit>
	./scripts/build-platform-release.sh

platform-deploy: ## Deploy the built platform runtime to capability workers; ARGS="--limit pi_workers"
	./infra/ansible/run-deploy-platform-runtime-local.sh $(ARGS)

platform-status: ## Read standing worker advertisements from the private jobs broker
	./scripts/platform-status.sh $(ARGS)

curator: ## Serve a local-only cohort curator; needs SOURCE_ID=; ARGS="--host 0.0.0.0" enables trusted-LAN access
	@test -n "$(SOURCE_ID)" || (echo "Set SOURCE_ID=<source-id>" >&2; exit 1)
	uv run python apps/review/review_server.py --source-id "$(SOURCE_ID)" $(ARGS)

dask-up: ## Build the image, start Jupyter, and deploy the Dask scheduler/worker Swarm stack (see infra/dask/README.md)
	./infra/dask/deploy-dask.sh

dask-down: ## Stop Jupyter and remove the Dask Swarm stack
	./infra/dask/deploy-dask.sh --down
