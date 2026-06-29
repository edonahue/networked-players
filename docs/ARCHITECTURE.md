# Architecture

## Guiding shape

Networked Players is a static-first data product backed by a rebuildable home-lab pipeline. The public application should not require the home environment to be available.

## Logical roles

| Role | Responsibility | Current direction |
| --- | --- | --- |
| Configuration control | Repeatable host setup and verification | Ansible from the coordination host |
| Orchestration control | Schedule and reconcile services | Single Docker Swarm manager initially |
| Durable state | PostgreSQL, Redis, manifests, canonical snapshots | Pinned to SSD-backed x86 host |
| Bounded workers | Independent background jobs over immutable inputs | Four ARM64 Raspberry Pi 3B nodes |
| Heavy build and analysis | Full ingest, image builds, compaction, benchmarks | Optional workstation, not required for uptime |
| Public delivery | Game, findings, static challenges | Static hosting first |
| Optional live delivery | Bounded path and challenge requests | Later API with graceful failure |

One machine may perform several logical roles, but the documentation should preserve the distinction.

## Data flow

```text
private seed supplied locally
→ source catalog retrieval
→ normalized, provenance-bearing records
→ versioned Parquet datasets
→ DuckDB transforms and validation
→ evidence-bearing graph snapshot
→ challenge and path generation
→ static publishable artifacts
→ optional bounded API indexes
```

## State and jobs

- PostgreSQL is reserved for mutable application state and searchable registries, not as the only analytical archive.
- Redis and RQ are the default direction for simple retryable operational jobs.
- Dask remains an optional experiment for a workload with real task dependencies or distributed analytical collections.
- Workers consume immutable, checksummed snapshots and reject jobs for a different version.

## Graph model

The source graph should preserve artist → release → artist evidence. An artist-only projection may support selected analysis, but it must not replace the source evidence model. NetworkX or similarly readable fixtures should validate correctness before optimized representations are trusted.

## Failure posture

- The public static experience remains useful when the cluster or live API is unavailable.
- A single Swarm manager is intentionally simple and not highly available.
- Reproducible configuration, versioned artifacts, state backups, and tested recovery mitigate—not erase—that limitation.
- No live endpoint is part of the initial release contract.
