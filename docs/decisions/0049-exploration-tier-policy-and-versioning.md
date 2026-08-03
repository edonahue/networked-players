# ADR 0049: Exploration-tier policy and versioning

- **Status:** Accepted
- **Date:** 2026-08-03
- **Related:** [ADR 0038](0038-hybrid-album-catalog-assembly.md), [ADR 0046](0046-record-routes-productionization.md)

## Context

The curated 140-album editorial/game catalog has been very useful for
quality-controlled game content, but arbitrary open-ended exploration and
path search (Phase 2's Connect Two Records / Network Explorer) need a larger
graph than 140 albums can support. The project's own principle is
measure-before-optimizing: no specific larger catalog size should be
committed to without evidence it's achievable and useful.

`rank_album_candidates`/`assemble_album_catalog`
(`packages/graph-core/.../analysis.py`) already support an arbitrary
`--target-count` — no new ranking or assembly logic was needed. What was
missing was (a) a way to run this measurement without risking the output
being confused with, or accidentally validated against, the real public
catalog, and (b) an actual measurement record.

## Decision

Add `exploration_corpus_version` (`packages/graph-core/.../analysis.py`), a
sibling to `_catalog_version` — identical fingerprint shape (sorted
`artist_id:main_release_id:master_id:year` over the resolved albums), but a
distinct `explore-v1-` prefix instead of `catalog-v1-`. This mirrors the
Record-Routes-vs-Connection-Guesser non-collision discipline (ADR 0046): two
concepts that can share a shape must never share a namespace.

Add a new CLI command, `rank-exploration-tier`, rather than repurposing the
existing exploratory `build-album-catalog` command. It wraps the identical
`assemble_album_catalog` call, then strips `catalog_version` from the result
and stamps `exploration_corpus_version` instead, adds an explicit
`"MEASUREMENT ONLY"` note, and — the actual code-level enforcement, not just
a docstring warning — **refuses to write its output anywhere outside
`local/`**. An exploration tier is never a publication candidate on its own;
this makes that a runtime guarantee, not a convention someone can forget.

Real measurement (`docs/EXPLORATION_TIER_COMPARISON.md`) ran this against the
real one-hop working set at 500- and 1,000-album targets. Both targets are
achievable given a sufficiently large ranked candidate pool (3,000 candidates
sufficed; 1,000 did not, undershooting 500 to 373 — a real, reported finding,
not glossed over). No specific tier is chosen for publication as a result —
that decision explicitly waits on Slice E's browser-feasibility measurement
and the connectivity/family-exclusion measurements the comparison doc
identifies as still open.

## Consequences

- Growing the exploration corpus later requires no new ranking/assembly
  code — only a decision about `--target-count` and enough candidate supply
  (this ADR's measurement shows candidate-pool size and target album count
  are separate parameters that must both be sized deliberately).
- `rank-exploration-tier`'s `local/`-only enforcement means a future
  contributor cannot accidentally wire an exploration tier into
  `apps/web/public/data/` without deliberately renaming the version field
  back to something the publication gate would need to recognize — a real
  friction point, intentionally.
- The comparison doc's "what this doesn't answer yet" section is a genuine
  scope boundary, not a placeholder: connectivity-at-scale and
  family-exclusion-at-scale measurement are real, identified follow-up work
  for whichever future slice proposes shipping a specific tier.

## Validation

`packages/graph-core/tests/test_analysis.py`: `exploration_corpus_version`'s
distinct-prefix/determinism properties, and fixture-scale coverage of
`assemble_album_catalog` at 500/1000 target counts (proving the existing
pipeline is already parametric at these scales without requiring the private
one-hop dataset in CI).
`packages/graph-core/tests/test_cli_rank_exploration_tier.py`: the CLI
refuses to write outside `local/`, and a successful run's output never
contains `catalog_version`.

## Revisit trigger

Revisit this ADR when a specific exploration tier is actually proposed for
publication — that decision needs its own slice covering the two open
measurements (connectivity-at-scale, family-exclusion-at-scale) and a real
publication contract (schema, validator, `PUBLIC_ARTIFACT_GROUPS` entry) the
way every other public artifact has one. Until then, `exploration_corpus_version`
identifies a local measurement run, not a publishable dataset.
