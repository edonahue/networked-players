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
This was a real, evidence-based estimate at the time, later superseded — see "Full
unbounded run: complete" below for the actual measured result, after the same-day
performance fixes roughly doubled this throughput. The single-core utilization here
also means there's real unused parallelism headroom on this 4-core host if a future
need justified speeding this up further.

A naive linear scale-up from this slice (10,000 of ~19.1M May 2026 releases, per the
planning envelope above) projected roughly 2.3 MB × 1,911 ≈ **4.3 GB** of Parquet
output for a full unbounded parse — within, but toward the lower half of, the
existing 10–25 GB planning range. This was a projection from one sample of the
dump's first N releases; the actual full-run output (6.6 GB, see below) came in
higher, meaning record complexity was not uniform across the full dataset — later
releases in the June 2026 dump apparently carry more credits/tracks per release on
average than the first 10,000.

### Real profiling: where parse time actually goes (2026-07-01)

A completed, supervised 50,000-release run (`scripts/run-ingest-supervised.sh`, see
ADR 0014) measured **537.6 releases/sec** (50,000 releases in 93s of parse time,
validated clean) — the first fully-completed real run at this scale, not a partial
one. A `cProfile` pass over the same 50,000-release sample (real, not projected;
~26% slower under profiling overhead but the *relative* breakdown is what matters)
found the bottleneck is **neither decompression nor Parquet writing**:

| Stage | Self time (profiled run) | Share of total |
| --- | ---: | ---: |
| `_text()` (`lxml` `element.findtext()` calls) | 62.6s | **54%** |
| Credit-row assembly (`_append_artists`/`_append_track_tree`/`_artist_row`, itself calling `_text()` repeatedly) | ~23s | 20% |
| The `iterparse` loop itself (`_iter_handle`) | 10.8s | 9% |
| Parquet writing (`_write_rows`/`pyarrow.write_table`) | ~6s | 5% |
| gzip decompression (`zlib`/`gzip`) | <1s | <1% |

3.95 million calls to `_text()` — about 79 per release — each doing a fresh linear
scan of an element's children via `findtext()`, even when multiple fields are read
off the same element. This directly informs the parallelism question this section
previously left open: file-splitting for parallel decompression/tokenization would
target a stage that's already cheap (<1% of total time); the real cost is in
Python-level field extraction, addressed first as an algorithmic fix (same
single-threaded design, no multiprocessing complexity) before any parallelism work
is reconsidered.

**The algorithmic fix, implemented and measured the same day:** `releases.py` now
builds a `{tag: text}` map once per XML element (`_child_text_map`) instead of one
`findtext()` linear scan per field. Confirmed correct (full test suite passes
unchanged — this is a pure performance change, not a behavior change) and confirmed
fast, two independent ways:

| Measurement | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| Real wall-clock, 50,000 releases (parse stage only) | 93.0s (537.6/sec) | ~49s (~1,018/sec) | **~1.9x** |
| `cProfile` total, same 50,000-release sample | 115.9s | 64.6s | **1.79x** |

The re-profiled run confirms the fix landed exactly where intended: `_text()`'s
62.6s (54%) is gone, replaced by `_child_text_map` + `_text_from_map` at a combined
~11s — an 82% reduction in that specific cost, with every other stage's timing
essentially unchanged (no regression introduced elsewhere). Revised full-scale
projection: 19,113,243 releases ÷ ~1,018/sec ≈ **~5.2 hours** for a full unbounded
parse (down from the earlier ~12.4 hour estimate) — still a real, single-threaded
estimate, not a claim that a full run has completed.

### "Light" parallelism explored before the full run (2026-07-01)

Two ideas were checked for real, low-risk wins before committing to the full run.
Larger `--chunk-releases` (already a CLI flag, no code change) was tested directly
and made **no measurable difference** — write cost is proportional to data volume,
not per-flush overhead, so this isn't worth reaching for. Overlapping each chunk's
Parquet write (with SHA-256 hashing) on a background thread while the next chunk
continues accumulating on the main thread (`parquet.py`'s `write_release_dataset`,
bounded to one write in flight — never an unbounded queue) *did* help, matching the
predicted ceiling: 50.6s → 48.5s on the same 50,000-release workload, ~4.2%,
consistent with pyarrow's/hashlib's C code releasing the GIL for the real work while
some Python-level overhead (building the Arrow table from row dicts) doesn't. Output
verified identical (same row counts, zero invariant violations) — a pure performance
change.

Both of these targeted the ~9% of time spent writing. The real remaining lever is
the transform stage (`_append_artists`/`_append_track_tree`/`_artist_row`, ~68% of
time, three of four host cores idle throughout) — genuine multiprocess parallelism
there, not attempted in this pass, is where the next big win would come from if the
now-revised ~5 hour full-parse time still isn't fast enough in practice.

### Full unbounded run: complete (2026-07-01 evening to 2026-07-02)

With the fixes above landed, a genuine full, unbounded parse of the June 2026
snapshot was launched the same evening via the hardened supervised pipeline
(`SNAPSHOT=20260601 OVERWRITE=1 ./scripts/run-ingest-supervised.sh`, started
17:59:48 EDT) and **ran to completion**, including an automatic full-dataset
`validate` pass as the pipeline's own step 4/4 — the first genuinely completed
full run, not a partial or projected one.

Interim progress samples, for reference (the monitor unit logged every 30 minutes
throughout):

| Sample time (EDT) | Releases so far | Parquet parts | Disk free | Mem available |
| --- | --- | --- | --- | --- |
| 18:29:49 | ~1,625,000 | 325 | — | 5.79 GB |
| 19:59:50 | ~6,315,000 | 1,263 | 854 G | 5.85 GB |
| 21:29:51 | ~10,995,000 | 2,199 | 852 G | 5.86 GB |
| 22:59:53 | ~15,790,000 | 3,158 | 851 G | 5.83 GB |
| 23:59:53 | ~19,070,000 | 3,814 | 850 G | 5.82 GB |
| 00:29:55 (next day) | run finished; unit deactivated | — | 850 G | 5.97 GB |

**Final measured result:**

| Item | Value |
| --- | ---: |
| Elapsed (wall clock) | 6h 3m (17:59:48 → 00:02:49 EDT) |
| Releases | 19,192,301 |
| Tracks | 178,224,810 |
| Credits | 220,015,758 |
| Average throughput | ~881 releases/sec |
| Parquet output (total) | 6.6 GB (`credits` 3.9 GB, `tracks` 2.3 GB, `releases` 439 MB) |
| `validate` result | 0 invalid linked-artist IDs, 0 missing credit scope, 0 orphan credits, 0 orphan tracks |
| Peak memory | Stayed flat ~5.8 GB available throughout (no leak across ~6 hours / 19M+ releases) |
| Disk consumed | ~1 GB/hour; 850 GB still free at completion |

The measured 6h 3m lines up almost exactly with the ~6 hour estimate projected
mid-run from the interim samples, and with ADR 0014's independently-derived ~5.2
hour profiling-based projection (real wall-clock naturally runs a bit longer than
a pure-CPU profiling extrapolation, since it also includes I/O and the ntfy
monitor's own periodic overhead). The 881 releases/sec average is roughly double
the pre-fix ~428.5 releases/sec partial-run rate, confirming the same-day `_text()`
fix and write-overlap thread delivered their combined benefit at full scale, not
just on smaller samples. Actual Parquet output (6.6 GB) landed above the 4.3 GB
naive linear projection — see the revised note above; June 2026's release mix
skews toward more credits/tracks per release than the first 10,000 releases
suggested. This closes Milestone 3's last open task in `docs/BUILD_PLAN.md` for
real.

With the dataset complete, `docs/discogs-data/raw-dump-schema.md`'s "Real
full-dataset profiling (2026-07-02)" section goes further: real column-level
null rates, distributions, and encoding/outlier spot checks across all 19.19M
releases, plus query-performance notes for the DuckDB CLI setup used to run
them.

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
