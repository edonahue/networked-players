# ADR 0033: Cohort connectivity scoring is memory-bounded and bidirectional — reach rows in DuckDB, not parent maps in Python

- **Status:** Accepted
- **Date:** 2026-07-09

## Context

ADR 0030 replaced per-pair `find_path` calls with one Python-resident BFS per unique
cohort artist (`_bfs_from_seed`), sharing a neighbor cache. A later change batched each
hop's frontier check and neighbor fetch into one DuckDB query per hop (a real latency win
over per-artist round-trips). Neither had ever completed a real cohort end to end: the
first real run of `discogs-community-best-albums` (25 albums, 25 unique artists) left
300/300 pairs `skipped` and a retry with a raised DuckDB memory limit was manually killed
at RSS 5.9 GB / 99.9% swap on a 7.6 GB host.

A read-only profiling pass this session (`local/analysis/.../memory-profile.json`)
measured the real one-hop dataset (`snapshot=20260601`) and found three distinct causes,
none of which "raise the memory limit" fixes:

1. **Every cohort seed is a hub by the release-count proxy** — minimum 712 credit rows,
   maximum 61,253, against the default `--max-frontier-expansion 300`. Under the shipped
   default the seed itself was capped at hop 0, so no BFS could start at all
   (`frontier_too_large` for every pair).
2. **Scratch-table population, not the query, was the timeout cause.** Inserting a
   17,612-id hub frontier one row per `executemany` statement took **54.3 s**; the batched
   query it fed took **1.06 s**. That alone blew the 30 s `--pair-timeout-seconds` for any
   hub seed (`seed_expansion_timeout` for the rest). Fixed separately (bulk `unnest`
   inserts, ~170× faster at that size) as the commit preceding this ADR.
3. **The retained BFS product is graph-sized.** The worst seed's hop-2 expansion is
   **5,387,707 edges reaching 445,106 distinct artists — roughly half the graph — ≈1–2 GB
   of Python dicts for one seed's one hop** (measured 178 bytes/edge). The shared
   `neighbor_cache` plus every seed's retained `parent_by_seed` map held all of it
   simultaneously. DuckDB itself never exceeded ~1.1 GB; the unbounded side was Python.
   Chunking the frontier bounds the *transient* spike but not the *retained* product, so
   it cannot fix this. Hop 3 would expand from a 445k-artist frontier — the whole graph.

## Decision

Score connectivity **bidirectionally, entirely inside DuckDB** (`_ReachScorer` in
`cohort_connectivity.py`), scorer_version bumped 2 → 3.

- **Reach rows, not parent dicts.** All search state lives in one DuckDB TEMP table
  `reach(seed_id, artist_id, parent_id, release_id, dist)`. Each hop is a single
  `INSERT … SELECT` (a `row_number()`-ranked self-join against `linked_credits` /
  `traversal_releases`, anti-joined against already-reached artists), so DuckDB's
  `memory_limit` + `temp_directory` spill bound the entire computation and Python never
  materializes edge payloads. The cross-seed neighbor cache is gone from the local path;
  hub reuse is DuckDB's problem now (shared materialized tables + its own buffer manager).
- **The frontier cap never applies to a seed at dist 0.** Since every real cohort seed is
  a hub, capping the seed means no cohort can score. The cap now filters which *reached*
  artists join the next frontier — and because it no longer protects Python memory, it is
  purely a time knob (real hop-1 frontier degrees measured p50 141, p90 ~2,100).
- **Meet-in-the-middle halves the required depth.** Each seed expands only to
  `expansion_depth = ceil(max_hops / 2)`. All pair distances come from one self-join over
  the reach table (`min(r1.dist + r2.dist)` where the two seeds' reaches share an artist).
  This is what makes real cohorts tractable at all — it eliminates hop 3's whole-graph
  expansion. A found path is reconstructed per pair by picking the deterministic best
  meeting artist and walking both sides' parent chains with point lookups, then feeding
  the existing `credit_rows` evidence/quality code unchanged.
- **A new guardrail `--max-reach-rows`** (default 2,000,000; worst real seed measured
  445,161 at depth 2) aborts a runaway seed to `skipped` / `reach_too_large` rather than
  grinding. The existing `--pair-timeout-seconds` still bounds each seed's expansion via
  `connection.interrupt()` plus a cooperative between-hops deadline check.
- **A `/proc/meminfo` preflight** (`cohort_preflight.memory_limit_preflight_failure`,
  wired into the CLI, bypassable with `--skip-preflight`) refuses a `--memory-limit` above
  half of MemAvailable — the measured swap-death mode. Missing/unparseable inputs never
  block (non-Linux, unknown limit syntax).
- **Parameters are recorded in the artifact.** The crashed run's settings were
  unrecoverable because `connectivity.json` recorded none. It now carries a
  `scoring_params` object (strategy, hops, depth, cap, timeouts, DuckDB settings), and a
  sibling local-only `scoring-diagnostics.json` carries per-seed reach sizes/timings and
  RSS checkpoints.

## Honesty semantics (unchanged intent, one new capability)

`found` is always trustworthy evidence. `no_path` is emitted only when both endpoints
expanded completely with nothing capped and no meeting artist within `max_hops`. Anything
else unmet is `skipped` with the most specific reason. **New:** because a capped artist is
still reachable *as a target*, a pair meeting *at* a capped hub is now `found` (neither
side needs to expand it). Only a path requiring travel *through* two consecutive capped
artists stays unprovable — a strictly smaller unprovable set than the single-direction
BFS, never larger.

## What this deliberately does not touch

`_bfs_from_seed`, the fleet job body (`infra/ansible/files/cohort_seed_bfs_job.py`), and
its cross-check test are left exactly as they are. `_bfs_from_seed` is retained solely as
the reference the fleet mirror is cross-checked against (ADR 0032); it is no longer on the
local scoring path. The fleet unit still ships full-depth single-direction parent maps and
carries the same unbounded-cache design — redesigning it (per-target chains, bidirectional
dispatch) is deferred to a later phase so the reference path stabilizes first, per the
plan this ADR implements. `precomputed_seed_results` (the fleet ingestion path) keeps its
prior pair-reconstruction logic unchanged. `challenge.py` and `cohort_resolve.py` are
unaffected. `max_workers` remains on the signature for compatibility but no longer fans
local scoring across cursors — with each hop a single DuckDB statement, `--threads` is the
effective parallelism lever.

## Consequences

The worst measured seed's depth-2 reach (445k rows) builds in ~68 s at a 1 GB DuckDB limit
on this Celeron J3455; the all-pairs meet self-join over ~11M rows is a single spillable
aggregate (~26 s for the same-shape hop-2 aggregate measured earlier). A full 25-seed
rescore is expected in the 15–20 minute range sequentially, less at a 3 GB limit — versus
never completing before. Memory is bounded by DuckDB's configured limit plus a small
constant, not by graph structure. The frontier cap can now be raised for coverage without
memory risk.

## Validation

`make check` green. New/changed tests: bulk scratch insert on 120k-id lists; a pair
meeting at a capped hub is `found`; a path through two consecutive capped hubs stays
`skipped`/`frontier_too_large`; a 3-hop pair found only by meeting in the middle alongside
a 1-hop and a genuinely-4-hop `no_path` in one run; a seed over the cap still expands from
dist 0; `reach_too_large`; `scoring_params` recorded and `scoring-diagnostics.json`
filled; the memory preflight (refuse/allow/never-block-on-unparseable/MiB parsing). The
timeout test now mocks `_ReachScorer._expand_hop` (the actual hot path). Real timing/RSS
numbers stay local per ADR 0018.

## Revisit triggers

Revisit the fleet job body's design (per-target chains, bidirectional dispatch) once the
local reach path is confirmed on real hardware and a worker holds a verified cache — the
current single-direction parent-map return is unworkable for hub seeds over Redis
(445k entries/seed). Revisit `--max-frontier-expansion`'s default now that it is a pure
time knob and a real degree distribution is measurable. Revisit `expansion_depth` if a
cohort needs `max_hops > 4` routinely (the split stays balanced, but the meet self-join
grows with each side's reach).
