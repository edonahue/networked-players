# Exploration tier comparison (Phase 2 Slice D)

Measured against the real, private-seed-derived one-hop working set (release
count and frontier-artist count already public in
`docs/discogs-data/one-hop-hub-artists.md`/`docs/DATA_SIZING.md`: 1,410,106
releases, 1,762 frontier artists). Method and code are public
(`rank_album_candidates`/`assemble_album_catalog` in
`packages/graph-core/.../analysis.py`, invoked via the new
`rank-exploration-tier` CLI command); real hardware timing is intentionally
omitted per ADR 0018 — only wall-clock order of magnitude is noted where it
affects feasibility, not a specific number tied to this host.

**This is a measurement record, not a publication decision.** No exploration
tier is shipped as a result of this document — see "What this doesn't answer
yet" below.

## Method

1. `rank-album-candidates` against the real one-hop dataset, gated by the
   same `studio-album-v1` release-format-scoring-index used to build the real
   140-album catalog (no masters/genre-style exclusion available in this
   pass — the same graceful degradation `rank_album_candidates` already
   supports when `--masters-root` is omitted).
2. `rank-exploration-tier --target-count {500,1000}` against that candidate
   pool, reusing the exact editorial-backbone-always-wins assembly logic that
   built the real 140-album catalog (ADR 0038) — the only difference is
   `target_count` and the output's version field
   (`exploration_corpus_version`, never `catalog_version` — ADR 0049).

## Results

| Tier | Candidate pool ranked | Editorial matched | Editorial missed | Candidates added | Albums achieved | Tier file size (uncompressed) |
|---|---:|---:|---:|---:|---:|---:|
| 140 (real, shipped) | — | 52 | (not re-measured here; see `docs/STUDIO_ALBUM_CATALOG_AUDIT.md`) | 88 | 140 | 36 KB (`catalog/albums.v1.json`) |
| 500 | 1,000 | 52 | 39 | **321** (undershoot — see below) | 373 | — |
| 500 | 3,000 | 52 | 39 | 448 | **500** | 111 KB |
| 1000 | 3,000 | 52 | 39 | 948 | **1,000** | 219 KB |

**First finding, honestly reported rather than glossed over**: ranking only
1,000 candidates undershoots a 500-album target (373 achieved, not 500) —
studio-album-policy filtering plus per-artist deduplication (an artist can
only fill one slot) thins the pool faster than the raw candidate count
suggests. Re-ranking at 3,000 candidates closed the gap and let both the
500- and 1,000-album tiers hit their exact target. This is the concrete,
measured argument for the plan's own "measure before optimizing" caution: a
tier's *candidate pool size* is a real, separate parameter from its
*target album count*, and undersizing the former silently produces a smaller
tier than requested rather than failing loudly. `rank-exploration-tier`
does not currently warn on this gap — worth a small follow-up (compare
`candidate_count_added` to `target_count - editorial_count` and flag the
shortfall) before this tooling is used for a real publication decision.

**Editorial hit rate**: 52 of the real 140-album catalog's editorial entries
matched at every tier (39 missed, identical across 500/1000) — editorial
matching is independent of `target_count`, exactly as `assemble_album_catalog`
guarantees (the editorial list is always resolved in full regardless of how
many candidate slots remain).

**Size scaling**: file size grew roughly linearly with album count (111 KB
at 500, 219 KB at 1000 — both a flat album list, not yet a full
`challenge.v2.json`-shaped artifact with paths/evidence). Extrapolating from
the real, published 140-album → 2.1 MB `challenge.v2.json` ratio (an
extrapolation, explicitly not a fresh measurement of a full path-and-evidence
artifact at these tiers): a similarly-shaped exploration artifact at 500
albums would project to roughly 7.5 MB, and at 1,000 albums roughly 15 MB —
both well past the existing 2.9 MB public high-water mark
(`routes/rounds.v1.json`). This is the central reason path/evidence
generation at these tiers cannot simply reuse the existing per-pair
`challenge.py` builder unmodified for publication; it is exactly what Slice E
measures before any tier is chosen for real path search.

## What this doesn't answer yet

- **Connectivity/reachability at scale**: whether albums in a 500- or
  1,000-album tier are actually mutually reachable within a bounded hop
  count is not measured here. The existing tools for this
  (`cohort_connectivity.py`'s bidirectional-BFS scorer, ADR 0030/0033) are
  built for a *resolved pair list*, not a flat album tier, and a full
  pairwise `find_path` sweep (C(500,2) ≈ 124,750 pairs) was judged too
  expensive to run in this pass. This is the natural next measurement before
  any tier is treated as a real path-search corpus (feeds directly into
  Slice E/F).
- **Family-exclusion trivial-pair rate at scale**: the plan's own stop
  condition (§ tripwires) requires comparing the 140-album baseline's
  family-exclusion trivial-pair rate against each larger tier's. Doing so
  needs a `build-artist-family-exclusions` run scoped to each tier's full
  artist-ID list followed by an actual round/path generation pass to observe
  trivial pairs in practice — deferred to whichever future slice actually
  proposes shipping a specific tier, rather than measured speculatively here.
- **A "first public exploration tier" decision**: deliberately not made.
  500 albums clears the achievability bar measured above; whether it is the
  *right* first tier depends on Slice E's browser-feasibility measurement
  (payload/parse/memory budget) and the two open items above.

## Versioning

Exploration tiers use `exploration_corpus_version` (`explore-v1-<snapshot>-
<hash>`, `packages/graph-core/.../analysis.py::exploration_corpus_version`),
never `catalog_version` — the two share their fingerprint algorithm but a
different prefix, so a tier artifact can never be confused with, or
accidentally pass validation against, the real editorial/game catalog (ADR
0049, mirroring the Record-Routes-vs-Connection-Guesser non-collision
discipline in ADR 0046). `rank-exploration-tier` refuses to write its output
anywhere outside `local/` — a tier is a measurement artifact, never a
publication candidate on its own.
