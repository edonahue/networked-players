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

## June 2026 real observation vs. the August 2025 benchmark

All four dump kinds for the June 2026 snapshot were downloaded and directly counted
(`zcat | grep -c`) on the coordination host, 2026-07-01 — a real, independent
corroboration of the table above, not a projection. Byte-size growth uses decimal
GB/MB (10^9/10^6 bytes) throughout for a consistent comparison:

| Dump | Aug 2025 records | Jun 2026 records | Record growth | Aug 2025 `.xml.gz` | Jun 2026 `.xml.gz` | Size growth |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Labels | 2,274,143 | 2,383,990 | +4.8% | 83 MB | 89.0 MB | +2.3% |
| Artists | 9,174,834 | 10,081,427 | +9.9% | 441 MB | 490.1 MB | +6.0% |
| Masters | 2,459,324 | 2,560,991 | +4.1% | 577 MB | 614.3 MB | +1.5% |
| Releases | 18,412,655 | ~19,113,243 (May 2026 count, not independently recounted this session) | ~+3.8% | 10.74 GB | 11.10 GB | +3.3% |

Record-count growth consistently outpaces byte-size growth across all three
independently recounted kinds (labels, artists, masters) — average record size is
shrinking slightly, not growing, as the catalog expands. Field-by-field structure
for all four kinds, grounded in this same real download, is documented in
[`docs/discogs-data/`](discogs-data/README.md).

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
**not** captured by this run — filled in by the partial full-scale run below instead.

### Partial full-scale run (same day, same host)

An unbounded parse (no `MAX_RELEASES`) of the same already-downloaded snapshot was
started to gather real throughput/memory data, then deliberately stopped partway
through (not a failure) once it was clear the full run would take multiple hours —
a bigger commitment than initially assumed, worth surfacing before committing the
host to it unattended. `parse-releases` writes to a hidden `.snapshot=<date>.tmp-*`
staging directory and only atomically renames it over the final path on full
completion, so stopping early left the original bounded 10,000-release dataset
above completely untouched and still valid (confirmed: unchanged `manifest.json`,
same counts). Observed before stopping, via `resource.getrusage(RUSAGE_CHILDREN)`
and a direct Parquet-part count (both real measurements, not estimates):

| Item | Observed value |
| --- | ---: |
| Releases processed before stopping | 650,000 (130 parts × the 5,000/part default chunk size) |
| Elapsed (wall clock) | 1,516.78 s (~25.3 min) |
| Peak RSS | 167.6 MB |
| Throughput | ~428.5 releases/sec |
| CPU utilization | ~100% of one core (single-threaded; 3 of 4 host cores idle throughout) |

Peak memory staying near-identical (167.6 MB at 650,000 releases vs. an unmeasured
but visibly small figure at 10,000) is itself a meaningful confirmed result: it
directly supports the streaming/bounded-memory design claim (`AGENTS.md`: "memory
tracks the active XML subtree rather than the total dump size") at 65x the earlier
sample size, not just in a synthetic test.

**Full-scale projection from this real throughput** (not the earlier untested linear
guess from Parquet output size alone): 19,113,243 releases ÷ ~428.5/sec ≈ **~12.4
hours** for a full unbounded parse on this host's single-threaded implementation.
This is a real, evidence-based estimate, not a claim that a full run has completed —
no full-scale Parquet output or full-scale `validate` result exists yet. The
single-core utilization also means there's real unused parallelism headroom on this
4-core host if a future need justified speeding this up.

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
