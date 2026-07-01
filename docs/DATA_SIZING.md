# Discogs data sizing and storage budget

## What is measured versus estimated

Exact object sizes change each month and were not retrievable from the clean CI runner used during initial research because the Discogs S3 endpoints returned HTTP 403. This document therefore separates a published benchmark from a 2026 planning projection. The checked-in downloader records exact bytes and SHA-256 after a successful local transfer.

## Published August 2025 benchmark

A third-party full-fidelity conversion of the August 2025 dumps used Zstandard Parquet and reported the following values:

| Dump | Records | `.xml.gz` | Parquet | Difference |
| --- | ---: | ---: | ---: | ---: |
| Labels | 2,274,143 | 83 MB | 72 MB | -13.2% |
| Artists | 9,174,834 | 441 MB | 397 MB | -9.9% |
| Masters | 2,459,324 | 577 MB | 537 MB | -6.7% |
| Releases | 18,412,655 | 10.74 GB | 10.14 GB | -5.5% |
| **Total** | **32,320,956** | **about 11.84 GB** | **about 11.15 GB** | **about -5.9%** |

The releases object dominates both conversion time and storage. Parquet's main benefit here is selective queries and partitioned processing, not a dramatic reduction from already-compressed gzip XML.

## June 2026 planning envelope

The most recently corroborated count available at the time of writing was the May 2026 release dump at 19,113,243 releases, about 3.8% above the August 2025 benchmark. Scaling bytes by record count is imperfect because record complexity changes, so use ranges rather than a point estimate.

| Layer | Practical planning range | Notes |
| --- | ---: | --- |
| One complete set of four compressed dumps | 12–15 GB | Retain exact downloaded bytes in the source manifest |
| Full-fidelity Parquet conversion | 11–15 GB | Similar order of magnitude to compressed XML |
| Project-focused release/track/credit Parquet | 10–25 GB | Depends on included nested fields, row splitting, and partition size |
| Temporary expanded XML | **0 GB by design** | Stream directly from gzip; do not keep expanded XML |
| DuckDB spill / compaction / failed staging | 25–75 GB | Workload-dependent; place on NVMe and enforce a free-space floor |
| Graph, indexes, challenges, manifests | 5–30 GB initially | Must be measured before selecting final graph representation |

These are capacity-planning ranges, not claims about a specific future snapshot.

## First real measurement (coordination host, 2026-07-01)

A bounded 10,000-release slice (`MAX_RELEASES=10000`) of the June 2026 snapshot ran
end to end on the ZimaBoard 832 coordination host — the first real run against real
hardware (Milestone 3). Observed, not projected:

| Item | Observed value |
| --- | ---: |
| Compressed releases dump (`.xml.gz`), full object | 11,099,074,063 bytes (~11 GB) |
| Releases parsed (bounded) | 10,000 |
| Tracks parsed | 59,009 |
| Credit rows parsed | 91,202 |
| Parquet output for this slice | 2.3 MB total (`credits` 1.4 MB, `tracks` 700 KB, `releases` 212 KB) |
| Validation invariants | All zero: invalid linked-artist IDs, missing credit scope, orphan credits, orphan tracks |

Two things worth stating plainly: the full `.xml.gz` object downloads regardless of
`MAX_RELEASES` (only parsing is bounded), so even a smoke-test run needs the full
~11 GB transfer and the full free-space floor. Elapsed time and peak memory were
**not** captured by this run — a real gap, not filled in here; a follow-up run should
wrap the pipeline with `/usr/bin/time -v` or similar.

A naive linear scale-up from this slice (10,000 of ~19.1M May 2026 releases, per the
planning envelope above) projects roughly 2.3 MB × 1,911 ≈ **4.3 GB** of Parquet
output for a full unbounded parse — within, but toward the lower half of, the
existing 10–25 GB planning range. This is a projection from one sample of the dump's
first N releases, not a new authoritative figure; record complexity may not be
uniform across the full dataset.

## Recommended 1 TB NVMe policy

The planned 1 TB project NVMe is sufficient with explicit retention:

- current verified compressed dump set;
- previous compressed dump set until the new snapshot is published;
- current canonical normalized dataset;
- previous canonical normalized dataset for rollback;
- one staging area for the next build;
- graph/publication artifacts and at least 20% free space.

A conservative steady-state budget is roughly 100–250 GB. A full rebuild with unusually large DuckDB spill or multiple abandoned staging directories can temporarily exceed that, so new full ingest should refuse to start below a configurable free-space threshold (initially 250 GB recommended). Do not retain expanded XML.

## Measuring the real snapshot

After download, the manifest contains exact compressed bytes and hashes. After conversion, `manifest.json` contains row counts and every Parquet file's bytes and hash. Record a local run with:

```bash
du -h local/raw/discogs/20260501/*
du -h -d 3 local/processed/discogs/snapshot=20260501
find local/processed/discogs/snapshot=20260501 -name '*.parquet' -printf '%s %p\n' | sort -n
```

A later benchmark issue should capture elapsed time, peak RSS, CPU, input bytes, output bytes, row counts, DuckDB spill, and hardware class for both the optional workstation and coordination host. The Pi workers should be benchmarked only on bounded partitions, not on the full raw dump.
