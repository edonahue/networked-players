# Architecture

## Guiding shape

Networked Players is a static-first data product backed by a rebuildable home-lab pipeline. The public application should not require the home environment to be available.

## Logical roles

| Role | Responsibility | Current direction |
| --- | --- | --- |
| Configuration control | Repeatable host setup and verification | Ansible from the coordination host |
| Acquisition control | Snapshot manifests, controlled downloads, checksums, terms review | SSD-backed coordination host |
| Orchestration control | Schedule and reconcile services | Single Docker Swarm manager initially |
| Durable state | PostgreSQL, Redis, manifests, canonical snapshots | Pinned to SSD-backed x86 host |
| Bounded workers | Independent jobs over immutable inputs | Four ARM64 Raspberry Pi 3B nodes |
| Heavy build and analysis | Full dump parse, compaction, image builds, benchmarks | Optional workstation, not required for uptime |
| Public delivery | Game, findings, static challenges | Static hosting first |
| Optional live delivery | Bounded path and challenge requests | Later API with graceful failure |

One machine may perform several logical roles, but the documentation should preserve the distinction.

## Data flow

```text
private seed supplied locally
→ verified Discogs snapshot manifest
→ checksummed compressed catalog object
→ streaming release normalization
→ versioned Parquet datasets
→ DuckDB transforms and validation
→ collection + one-hop filtered corpus
→ evidence-bearing graph snapshot
→ challenge and path generation
→ static publishable artifacts
→ optional bounded API indexes
```

## Discogs acquisition boundary

The private collection contributes release IDs only. Monthly dumps are the canonical bulk catalog source. A later API adapter may fill explicit gaps or inspect records newer than the selected dump, but it does not become a prerequisite for reproducible bulk builds.

Anonymous bucket listing is not assumed. A manifest may be generated offline from an explicit monthly date and edited to use an official object URL obtained through a browser or documented source. Successful downloads add exact size and SHA-256 metadata. See `DISCOGS_INGESTION.md`.

## Parsing and partitioning

The release parser reads gzip sequentially with `lxml.iterparse`, clears completed elements, and writes bounded Zstandard Parquet parts. This avoids an expanded XML copy and bounds memory. Release, track, and credit rows preserve evidence scope and original role text.

The parser itself is initially single-process. The optional workstation is preferred for full conversion. The coordination host can run limited slices and retains canonical results. Safe distributed work starts over immutable Parquet or graph partitions; a Pi worker should not download or inflate the full releases object.

## State and jobs

- PostgreSQL is reserved for mutable application state and searchable registries, not as the only analytical archive.
- Redis and RQ are the default direction for simple retryable operational jobs.
- Dask remains an optional experiment for a workload with real task dependencies or distributed analytical collections.
- Workers consume immutable, checksummed snapshots and reject jobs for a different version.
- Canonical datasets publish only after manifest, row-count, identity, and evidence validation.

## Graph model

The source graph preserves artist → release → artist evidence. An artist-only projection may support selected analysis, but it must not replace the source evidence model. A linked Discogs artist ID identifies a playable artist node; a non-linked credited name remains evidence but does not become a synthetic identity automatically. NetworkX or similarly readable fixtures should validate correctness before optimized representations are trusted.

## Failure posture

- The public static experience remains useful when the cluster or live API is unavailable.
- A single Swarm manager is intentionally simple and not highly available.
- Reproducible configuration, versioned artifacts, state backups, and tested recovery mitigate—not erase—that limitation.
- A failed download remains a `.part` file; a failed dataset remains staging and cannot replace the prior canonical snapshot.
- No live endpoint is part of the initial release contract.
