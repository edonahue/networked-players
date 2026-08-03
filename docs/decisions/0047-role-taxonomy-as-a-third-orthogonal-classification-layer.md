# ADR 0047: A role taxonomy as a third, orthogonal classification layer

- **Status:** Accepted
- **Date:** 2026-08-03
- **Extends:** [ADR 0035](0035-track-scoped-credit-edges.md) and
  [ADR 0039](0039-performer-allowlist-layered-for-game-rounds.md) without modifying either

## Context

The project already has two role-related classification layers, deliberately kept
separate:

- `graph.py`'s `_NON_COLLABORATIVE_ROLE_TOKENS` / `edge_ineligible_role` — a
  **denylist** answering "does this role justify a collaboration edge at all,"
  permissive by default (an unrecognized role stays edge-eligible).
- `eligibility.py`'s `_PERFORMER_ROLE_TOKENS` / `is_performer_role` — a narrower
  **allowlist** answering "did this specific person sing or play an instrument,"
  fail-closed by default, used only by game-round generation (ADR 0039).

Neither answers a question Phase 2's product work needs: "what *kind* of
contribution is this" — for display on a contributor page, for role-filtered
fading in a network explorer, and for role-aware game-mode candidate counting.
Studio roles (Producer, Engineer, Mixed By, Mastered By, Arranged By, Recorded
By) are explicitly named in `graph.py`'s own comments as edge-eligible, but
nothing in the codebase classifies them into a displayable category — they are
only ever excluded from the game's performer allowlist.

`eligibility.py` already has a small piece of this: `_ROLE_CATEGORY_BY_TOKEN`
maps each performer token to a display category (`vocals`, `guitar`, `bass`, ...)
for the game's contributor chips. That precedent is reused directly rather than
re-derived.

## Decision

Add `packages/graph-core/.../role_taxonomy.py`, a **third**, independent module.
It exports `RoleCategory` (an eleven-value bounded enum: `vocals`, `strings`,
`percussion_keys`, `brass_woodwind`, `production`, `engineering`, `arrangement`,
`composition`, `rework`, `packaging_business`, `unknown`), `classify_role(role_text)`
(returns every distinct category present across a comma-separated role string),
`primary_role_category`, and a DuckDB-mirrored `classify_role_sql`, kept in step
by `test_classify_role_matches_the_sql`.

Each category carries a `traversable: bool` in `CATEGORY_TRAVERSABLE` — this is a
**read** of `graph.py`'s existing `credit_edges_sql` behavior re-expressed for
display (composition/rework/packaging-business roles are the ones already in
`_NON_COLLABORATIVE_ROLE_TOKENS`; everything else, including `unknown`, is
already edge-eligible today). It documents existing behavior; it must never
become a new gate consulted by `graph.py` or `eligibility.py`.

Performer tokens are reused, not re-typed: `role_taxonomy.py` imports
`_PERFORMER_ROLE_TOKENS`/`_ROLE_CATEGORY_BY_TOKEN` from `eligibility.py` and
remaps each fine-grained display category into this taxonomy's coarser buckets
via `_PERFORMANCE_SUBCATEGORY` — one source of truth for "what does `guitar`
mean." Non-collaborative tokens are reused the same way from `graph.py`'s
`_NON_COLLABORATIVE_ROLE_TOKENS`, partitioned into `composition`/`rework`/
`packaging_business` (`test_non_collaborative_tokens_are_fully_partitioned`
asserts the partition is exact and disjoint, so a future addition to that
denylist that isn't triaged here fails loudly instead of silently becoming
`unknown`). New `production`/`engineering`/`arrangement` tokens are seeded only
from role strings already named in this project (`graph.py`'s own docstring,
`eligibility.py`'s `ROLE_PARITY_CASES`, and `docs/discogs-data/
one-hop-hub-artists.md`'s real hub-artist roles) — deliberately narrow to
start.

`UNKNOWN` is explicit and first-class: an unmatched component classifies as
`unknown`, never silently folded into an adjacent category. A `classify-roles`
CLI diagnostic (`corpus_coverage_report_from_dataset`) reports the percentage
of `role_text` values classified and the most frequent unmatched strings, over
a local dataset only — it is a coverage report, never a build gate, and its
output is never published (the same `local/analysis/` posture as cohort
connectivity diagnostics).

This module is allowed to import both `graph.py` and `eligibility.py`. ADR
0039's "must never be imported by `graph.py`/`challenge.py`/cohort code" rule
applies to `eligibility.py` specifically, to protect the album/cohort graph
from the game's narrower rule leaking backward — it does not forbid a new,
independent consumer reading from both existing layers.

## Consequences

- Contributor pages (Slice C), the network explorer's role-filtered fading
  (Slice G), and role-aware game-mode candidate measurement (Slice H) all have
  one shared, tested vocabulary to build against, rather than each inventing
  its own ad hoc categorization.
- The taxonomy will always be incomplete relative to the full space of Discogs
  role text (`docs/discogs-data/one-hop-hub-artists.md` observed 3,115 distinct
  role-text variants from just 20 artists) — `unknown` makes that honest and
  visible rather than hidden behind a wrong guess.
- Extending the taxonomy is a config-only, human-reviewable change (adding a
  token to a flat frozenset), the same auditability property
  `placeholder_artists.json` and `_PERFORMER_ROLE_TOKENS` already established.

## Validation

`packages/graph-core/tests/test_role_taxonomy.py` covers: the Python/SQL parity
fixture across real difficult role strings already used elsewhere in this
project; every `RoleCategory` having a `CATEGORY_TRAVERSABLE` entry; every
`eligibility.py` display category being mapped into a taxonomy bucket; the
non-collaborative token partition being exact and disjoint; a genuinely novel
role string classifying as `unknown` rather than a guessed category; and the
`corpus_coverage_report` diagnostic's shape over a synthetic corpus.
`packages/graph-core/tests/test_cli_classify_roles.py` covers the CLI wiring.

## Revisit trigger

Extend `_PRODUCTION_TOKENS`/`_ENGINEERING_TOKENS`/`_ARRANGEMENT_TOKENS` only
after reviewing real unmatched role strings surfaced by `classify-roles`'
diagnostic, never by guessing. If a diff ever wires `CATEGORY_TRAVERSABLE`
into an `if` branch inside `graph.py` or `eligibility.py` — rather than reading
it for display — that is the layering violation this ADR exists to prevent;
revert it and re-derive the need as a change to the underlying denylist or
allowlist directly, with its own review.
