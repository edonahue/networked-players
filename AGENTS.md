# Agent guidance

This repository is scaffold-first but now contains a small working Discogs ingestion slice. Automated contributors must preserve the distinction between a tested vertical slice and a production-ready pipeline.

## Required behavior

- Read `README.md`, `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/DISCOGS_INGESTION.md`, `docs/DATA_AND_RIGHTS.md`, and `docs/PUBLIC_PRIVATE_BOUNDARY.md` before proposing architecture changes.
- Do not claim that an application, service, cluster deployment, full dump conversion, benchmark, or public dataset exists until the repository contains evidence for it.
- Keep fixtures synthetic and reproducible.
- Never add real secrets, addresses, hostnames, collection exports, raw dumps, runtime inventories, backup locations, or deployment identities.
- Prefer small vertical slices over broad placeholder frameworks.
- Add an architecture decision record when changing a settled direction.
- Preserve static-first failure behavior: a home-hosted service must not become a requirement for the core public experience.
- Treat Raspberry Pi 3B workers as constrained 1 GB ARM64 nodes; bound memory, payload size, concurrency, and job duration.
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
