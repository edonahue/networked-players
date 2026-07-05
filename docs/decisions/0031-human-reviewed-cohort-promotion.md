# ADR 0031: Human-reviewed cohort promotion uses a selection file, not CLI-flag pair selection

- **Status:** Accepted
- **Date:** 2026-07-05

## Context

`docs/DATA_AND_RIGHTS.md` and `docs/PUBLIC_PRIVATE_BOUNDARY.md` both already commit to "a
separate, explicit, human-reviewed promotion step (never the extraction pipeline itself)"
existing before anything from the curated-cohort pipeline moves toward a committed file —
but no such step existed in code. `local/analysis/cohorts/<source-id>/connectivity.json`
(PR #32, hub-hang-fixed by `e0bce4a`) is the last local-only intermediate; this PR builds
the promotion step those docs already promised.

Two ways to let an operator approve specific pairs were considered:

- **Option A — a selection file.** A small, hand-authored JSON naming `approved_pairs[]`
  by album ID, with a cohort-wide `allow_flagged_pairs` override.
- **Option B — CLI flags.** `--approve-pair master-123:master-456` repeated per pair.

## Decision

**Option A.** A cohort worth promoting is likely to have more than a handful of pairs —
CLI flags don't scale past a few approvals, don't produce a reviewable artifact (a shell
history entry isn't a record), and don't have anywhere natural to attach a per-pair review
note. A selection file is itself a small, git-ignorable, diffable record of what a human
actually decided and why; that audit trail is worth the "one more private file format" cost
Erich himself flagged as Option A's only real con.

**A single, unified `allow_flagged_pairs` check**, not one rule per weak-connection
category. `cohort_connectivity.py`'s `warnings[]` field is already populated by
`_pair_warnings` exactly for the two categories that matter here
(`non_performer_only`, `placeholder_artist_hop`) — re-deriving those two cases separately in
the promotion layer would duplicate logic that already exists and is already tested.
`allow_flagged_pairs` can be set cohort-wide (in the selection file's top level) or per-pair
(on an individual `approved_pairs[]` entry) — the per-pair override exists so approving one
genuinely-fine flagged pair doesn't force blanket approval of every other flagged pair in
the same cohort.

**Reviewer identity and per-pair review notes stay private.** The selection file's
`reviewed_by` and each `approved_pairs[]` entry's own `review_note` are never carried into
the published artifact — only a single, optional, cohort-level `review_note` is (see
`data/contracts/playable-cohort-v1.md`). A promoted artifact needs to say *when* it was
reviewed and, optionally, a short public-facing note; it doesn't need to say *who* reviewed
it or expose a reviewer's private per-pair commentary.

**`draft-cohort-review` (a selection-file template generator) is deferred.** It's a genuine
convenience — filtering `connectivity.json` to its `"found"`, unflagged pairs and emitting a
starter `approved_pairs[]` list — but not required for the core path: an operator can
hand-write a short selection file directly for an early cohort of a dozen or so albums.
Revisit once a real cohort's pair count makes hand-authoring the selection file genuinely
painful.

## Consequences

`promote_playable_cohort` (`cohort_promote.py`) is deliberately pure Python — no
`CreditGraph`/DuckDB dependency anywhere in its call graph, the same shape
`summarize_connectivity` already established — since it only reads/writes already-computed
JSON. This makes it a strong future Pi-ambient-job candidate (validate a selection file,
re-run promotion) without needing the heavier graph dependency, though wiring that up is
explicitly out of this PR's scope.

`playable-cohort-v1.json` is the one artifact in this whole pipeline meant to be committed.
Its `promote-playable-cohort` CLI command prints the same prepublish-checklist reminder
`build-challenge-from-dump` already prints, pointing at
`docs/PUBLIC_PRIVATE_BOUNDARY.md` — `validate_playable_cohort()` checks structure and known
leak patterns, not editorial judgment; a human still decides whether a cohort is actually
ready to ship.

`docs/PUBLIC_PRIVATE_BOUNDARY.md`'s prior closing note ("nothing in that pipeline stage
publishes anything") is now stale and is updated alongside this ADR.

## Validation

`make check` green with the new module's tests (synthetic fixtures only — a real,
Discogs-derived promoted cohort is committed only with Erich's own explicit review and
go-ahead, never as a byproduct of this PR), covering: clean promotion, rejection of
`no_path`/`skipped`/absent-in-connectivity approved pairs, rejection and then
allowed-with-override promotion of a flagged pair, rejection of a zero-pair promotion,
rejection of a `dataset_snapshot_date`/`source_url` mismatch between `resolved.json` and
`connectivity.json`, the forbidden-substring scan, and the "worked with"/"collaborated
with"/"influenced" tone scan.

## Revisit trigger

Revisit `draft-cohort-review` once a real cohort's pair count makes hand-authoring a
selection file painful. Revisit whether reviewer identity should ever be published (e.g. a
public "curated by" credit) only if Erich explicitly wants that — the current default is to
keep it private, not because it's sensitive, but because nothing in this pipeline currently
needs it published.
