# ADR 0030: Cohort connectivity scoring uses a per-cohort-artist BFS with a shared neighbor cache, not per-pair `CreditGraph.find_path` calls

- **Status:** Accepted
- **Date:** 2026-07-05

## Context

ADR 0029 recorded a real smoke test hang as a confirmed-not-hypothetical performance risk
but deferred fixing it, since PR 3's job was to compute and flag, not to be fast. That
smoke test's failure mode was reproduced and diagnosed directly against the real one-hop
dataset (`local/processed/discogs-onehop/snapshot=20260601`, 916,878 artists) on this host:

1. **A real hub artist is the root cause.** Sampling real artist IDs from the dataset and
   calling `CreditGraph.neighbors()` on each individually: one artist has 1,857 neighbors
   (several seconds per call); two others have 833 and 564 (roughly a second each). A hub
   is a real, legitimately prolific person — a heavily-covered songwriter or engineer —
   not a placeholder ADR 0026/0027 already exclude.
2. **`CreditGraph.find_path`'s BFS pays a hub's cost once per pair, with no caching.**
   `--max-hops 2` did not help in the original smoke test's reduced retry (6 albums, 15
   pairs) — a hub can dominate cost as early as hop 1 if it happens to be a resolved
   cohort artist's direct neighbor. For an N-artist cohort, up to O(N²) pairs can each
   independently pay for the same hub's expensive fan-out query.
3. **Neither `CreditGraph.open()` nor `export_graph_snapshot()` ever set DuckDB's
   `temp_directory`.** On this host, that means spilling defaults to `.tmp/` relative to
   the process's CWD, which sits on a small boot disk separate from the much larger volume
   the real datasets live on. A real attempt to run `export-graph-snapshot` against the
   full one-hop dataset crashed after a long run with "No space left on device" as a direct
   result of this.
4. **A whole-dataset materialized adjacency snapshot (`graph-snapshot-v1`) is not
   currently a viable substrate on this hardware.** Beyond the crash above, a *cheaper*
   version of the same self-join shape — a bare per-artist degree count, not the full
   `edges` table with release-ID lists — was re-run with `temp_directory` correctly
   configured (ruling out the disk-space explanation) and still did not complete within a
   200-second budget. This is real evidence that the self-join across the whole dataset is
   expensive at this scale independent of the disk bug, not just unbuilt.

## Decision

**Fix the `temp_directory` omission unconditionally** in both `CreditGraph.open()` and
`export_graph_snapshot()` (`temp_dir: Path | None = None`, defaulting alongside the
dataset/output rather than CWD-relative `.tmp/`, following `onehop.py`'s existing
pattern). This is a correctness fix independent of everything else below.

**Do not build a whole-dataset materialized adjacency substrate in this PR.** The evidence
above says it isn't currently practical on this hardware. Instead, `score_pairs`
(`cohort_connectivity.py`) now computes connectivity using **one BFS per unique artist in
the cohort** (not one BFS per pair), via a new `_bfs_from_seed` helper built on the
already-existing `CreditGraph.neighbors()` — the same `linked_credits`/`traversal_releases`
self-join semantics as `find_path` and `graph-snapshot-v1`, just invoked once per node
instead of once per pair. All seeds' BFS runs share a single neighbor cache, so a hub
touched from more than one seed's frontier is queried via `neighbors()` **at most once**
per scoring run, however many pairs it happens to sit on — this is the actual fix for the
confirmed O(pairs) redundant-hub-query cost. For an N-artist cohort this is O(N) expensive
lookups in the worst case (every artist a hub) instead of O(N²), and typically far fewer in
practice since most artists aren't hubs. Path reconstruction for a specific pair is a cheap
dict walk over the relevant seed's already-computed parent pointers.

`CreditGraph.find_path` (with a new optional `max_frontier_expansion` parameter, see below)
is kept as graph-core's public single-pair API and as this module's reference
implementation — tests assert the BFS-with-cache mechanism and `find_path` produce
identical results on small synthetic graphs. It is not deleted or changed in a way that
alters `challenge.py`'s existing behavior (the default `max_frontier_expansion=None` is
uncapped, exactly matching prior behavior for any caller that doesn't pass it).

**Two operator-tunable guardrails**, applied as an unconditional safety net regardless of
the substrate:

- **`max_frontier_expansion`** (CLI: `--max-frontier-expansion`, default 300): a cheap
  release-count proxy (`CreditGraph.credit_row_count`, a single-table count with no
  self-join) checked before expanding a node's neighbors. Above the threshold, the node is
  excluded from *expansion* (its own edges aren't explored) but can still be *reached* as a
  target via another artist's edges. This is a heuristic seeded from the real fan-out
  numbers observed this session, not a precise percentile — a full degree distribution was
  attempted and did not complete (see point 4 above), so this default is deliberately
  described as a starting point, not false precision.
- **`pair_timeout_seconds`** (CLI: `--pair-timeout-seconds`, default 30.0): a wall-clock
  budget around each seed's own BFS (not each pair), enforced via DuckDB's own
  `connection.interrupt()` (confirmed by a direct test this session to raise
  `duckdb.InterruptException` and leave the connection usable afterward) plus a cooperative
  elapsed-time check between frontier steps, so a single pathologically slow query and a
  string of many small ones are both bounded.

**A new `status: "skipped"` value**, with a `skip_reason` (`"frontier_too_large"` or
`"seed_expansion_timeout"`), added to `album-cohort-connectivity-v1.md` (`scorer_version`
bumped 1 → 2). A pair is `"skipped"` only when *neither* endpoint's search could confirm an
answer; if either endpoint's own BFS completed cleanly, that result (a found path, or a
genuine absence of one) is used, checking both directions before giving up. This preserves
the project's standing rule that nothing is ever silently dropped or silently guessed:
`"skipped"` is a distinct, honest state, never conflated with a confirmed `"no_path"`.

## Consequences

Real cohort scoring on the production one-hop dataset should now complete in bounded time
instead of hanging, because the redundant per-pair hub cost is eliminated by the shared
neighbor cache — this is the primary fix. The guardrails exist for the residual case where
a cohort's own artists include a genuine hub (whose own expansion is unavoidable at least
once): that cost is now bounded and honestly reported via `"skipped"` rather than
hanging or lying. `challenge.py` is completely unaffected — no shared traversal filtering
changed, and `find_path`'s new parameter defaults to its exact prior behavior.

Fixing `CreditGraph`'s traversal to match `onehop.py`'s broader exclusion set (ADR 0029's
deferred option) remains deferred: no cohort has ever finished scoring for real yet, so
there's still no data on how common flagged pairs actually are in practice. This PR is a
prerequisite for gathering that evidence, not a substitute for the decision.

A whole-dataset `graph-snapshot-v1` materialization remains a documented, not-yet-viable
idea — nothing in this PR depends on it, and the tool (`export-graph-snapshot`) still
exists and is still useful for smaller datasets; it's just not the substrate cohort scoring
uses now.

## Validation

`make check` green, including new tests: `credit_row_count`/`interrupt()` behavior,
`find_path`'s `max_frontier_expansion` raising `FrontierTooLargeError` only when the only
route to a target required expanding a capped node (and still succeeding via an
uncapped alternate route), `CreditGraph.open()`/`export_graph_snapshot()` actually setting
`temp_directory`, `score_pairs`'s BFS-with-cache substrate producing results identical to
per-pair `find_path` calls on the shared synthetic fixture graph, a deterministic
`seed_expansion_timeout` test (a slow synthetic `fn` through `_run_with_timeout`, not a
real-timing race), `validate_connectivity`'s new `skip_reason`/`"skipped"` enforcement, and
a `review-report.md` regression covering the new "Skipped pairs" section. Real timing
numbers stay local, never committed, per ADR 0018's convention.

## Revisit trigger

Revisit `max_frontier_expansion`'s default once a full degree distribution can actually be
computed (this session's attempt didn't finish) — the current default is a reasonable
starting point from partial evidence, not a validated percentile. Revisit whether a
whole-dataset `graph-snapshot-v1` substrate is worth building once the per-cohort BFS
approach is measured against real, larger cohorts and a genuine plateau is found (many
cohorts sharing heavy overlap in artists would amortize a shared precomputed snapshot
better than this PR's fully in-memory, per-run cache). Revisit ADR 0029's
traversal-semantics-fix deferral once real cohorts can complete scoring and produce actual
flagged-pair-rate data.
