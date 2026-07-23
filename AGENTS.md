# Agent guidance

This repository is scaffold-first but now contains a small working Discogs ingestion slice. Automated contributors must preserve the distinction between a tested vertical slice and a production-ready pipeline.

## Setup and commands

- The `Makefile` is the canonical command surface; prefer it over ad-hoc commands.
- Prerequisites: `uv`, Python 3.12+, and the `libxml2`/`libxslt` dev headers for `lxml` (see `README.md`).
- `make setup` installs dependencies (`uv sync --extra dev --extra jobs`).
- `make check` runs every gate CI runs (Ruff lint, Ruff format check, mypy, pytest, `validate-public-artifacts` against the real committed artifacts under `apps/web/public/data/`, and `validate-album-catalog-audit` against the committed inclusion-audit record under `docs/data/`). Run it before reporting a change complete, and report anything you did not exercise.
- A real Discogs ingestion is operator work: see `docs/OPERATOR_SETUP.md` and `scripts/run-ingest.sh`. Never run a full raw dump as a Pi job.

## Agent tooling

This file is the canonical, tool-agnostic guidance. Both supported CLI agents load it:

- **Codex** reads `AGENTS.md` natively (root and nested, merged by directory).
- **Claude Code** loads `CLAUDE.md`, which imports this file via `@AGENTS.md`; edit guidance here, not there.
- Nested `AGENTS.md` (each with a one-line `CLAUDE.md` import) exist for `apps/web/` (Node/npm, not `uv`) and `packages/catalog/`.
- `.claude/settings.json` allowlists safe commands (`make`, `uv run` checks, read-only `git`) and denies reads of secrets and `data/private/`. Personal overrides go in the git-ignored `CLAUDE.local.md` / `.claude/settings.local.json`.

## Required behavior

- Read `README.md`, `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/DISCOGS_INGESTION.md`, `docs/DATA_AND_RIGHTS.md`, and `docs/PUBLIC_PRIVATE_BOUNDARY.md` before proposing architecture changes.
- Do not claim that an application, service, cluster deployment, full dump conversion, benchmark, or public dataset exists until the repository contains evidence for it.
- Keep fixtures synthetic and reproducible.
- Never add real secrets, addresses, hostnames, collection exports, raw dumps, runtime inventories, backup locations, or deployment identities.
- Prefer small vertical slices over broad placeholder frameworks.
- Add an architecture decision record when changing a settled direction.
- Preserve static-first failure behavior: a home-hosted service must not become a requirement for the core public experience.
- Treat Raspberry Pi 3B workers as constrained 1 GB ARM64 nodes; bound memory, payload size, concurrency, and job duration.
- Prefer parallel/concurrent execution across available cores and worker nodes for batchable or repeated work (e.g. batch a per-item DuckDB loop into one query, or fan work out across `CreditGraph.cursor()`/worker nodes), unless it compromises safety, correctness, or measurably regresses performance.
- Keep personal collection membership local even when the import mechanism is public.

## Discogs-specific rules

- Monthly dumps are the default bulk catalog source; the private collection is a release-ID seed, not a publishable dataset.
- Do not add an API dependency to bulk ingestion or distribute API credentials to workers or browsers.
- Preserve release-level evidence, source snapshot, source URL, parser/schema versions, and original role text.
- Keep PAN identity (`artist_id`) separate from ANV display text.
- Retain non-linked names as evidence but do not silently create playable artist identities for them.
- Do not infer artistic influence, relationships, or intent from a shared credit.
- Stream compressed XML and clear processed elements. Do not add expanded XML as a required intermediate.
- A full raw release dump is workstation or coordination-host work, not a Pi job. Pi jobs consume immutable, checksummed, bounded partitions.
- Any sizing claim must identify whether it is observed, sourced, projected, or measured locally.

## Working conventions

- Put user-facing applications in `apps/`.
- Put reusable domain logic in `packages/`.
- Put public schemas and synthetic fixtures in `data/`.
- Put infrastructure examples in `infra/`; real inventories remain local and ignored.
- Put cross-cutting decisions and design documentation in `docs/`.
- Python targets 3.12 and uses `uv`, Ruff, mypy, and pytest.
- Do not introduce another parser framework, database, queue, graph engine, or monorepo tool without a measured implementation need and an ADR.

## Validation expectations

Run the smallest relevant checks and report what was not exercised. Parser changes should cover synthetic release and track credits, PAN/ANV behavior, non-linked contributors, bounded early termination, and malformed-input failure. Parquet changes should round-trip through DuckDB. Benchmarks must record hardware, dataset version, method, input/output bytes, elapsed time, and peak memory rather than reporting unsupported impressions.
