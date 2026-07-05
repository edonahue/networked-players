# ADR 0027: Exclude pure non-performer role credits from the one-hop frontier

- **Status:** Accepted
- **Date:** 2026-07-04

## Context

[ADR 0026](0026-exclude-placeholder-artists-from-one-hop-frontier.md) excluded two
Discogs placeholder identities ("Various Artists", "Trad.") from one-hop frontier
eligibility, reducing the real run's retained-release count from 4,121,127 to 2,999,567
— still roughly 15.6% of the full 19,192,301-release catalog. `docs/discogs-data/one-hop-hub-artists.md`
identified the remaining volume as dominated by real, individually legitimate hub
artists: heavily-covered songwriters and extremely prolific mastering/recording
engineers.

A follow-up, read-only investigation (same document) checked whether the *role* a hub
artist is credited under, not the artist's identity, better explains the explosion.
Across the top ~20 real hub artists, releases connecting *only* through a role like
"Mastered By," "Written-By," "Producer," or "Arranged By" — with no performer role and
no main-artist credit — accounted for the large majority of their non-main-artist credit
volume. A mastering engineer's name appearing on a release is real and verifiable, but it
is not the kind of connection this game is about: it says nothing about who played,
sang, or performed on anything.

## Decision

`expand_one_hop`'s frontier and retention queries both gain a role filter, applied
identically to keep the two passes' notion of "eligible credit" consistent:

A credit counts as **performer-caliber** — eligible for frontier membership and
retention — when its `role_text` is `NULL` (a main-artist credit, from a release's own
`<artists>` block, always eligible) **or** contains at least one comma-separated
component that is not in a fixed `_NON_PERFORMER_ROLE_TOKENS` list (`onehop.py`):
`written-by`, `mastered by`, `mixed by`, `recorded by`, `lacquer cut by`, `arranged by`,
`liner notes`, `composed by`, `lyrics by`, `music by`, `words by`, `engineer`,
`producer`, `co-producer`, `design`, `design concept`, `photography by`. A credit is
excluded only when **every** component of a non-null role matches this list — a mixed
credit like "Producer, Vocals" still counts, since "Vocals" survives.

An unlisted or unrecognized role token always defaults to *eligible* — the list can only
under-filter (miss a role that arguably should be excluded), never silently over-filter
a role nobody reviewed. Evidence is unaffected: a retained release still keeps every
credit row, including excluded-role and placeholder-artist credits — this changes only
what counts as a *hop*, never what's shown as *evidence* for a release already retained
by some other path.

**"Producer" is a genuinely debatable inclusion.** A producer's creative involvement can
be much more personal than a mastering engineer's "make the levels right" role, and
reasonable people could argue it belongs on the performer side. It's included here
because that's what was actually measured and shown to the operator during this
investigation (`docs/discogs-data/one-hop-hub-artists.md`'s role-split diagnostic); if
this turns out to exclude connections that feel wrong once real gameplay data is
reviewed, moving "producer" off this list is a one-line change, not a redesign.

## Consequences

The frontier/retention filter now depends on `role_text`, which is read from disk in
both DuckDB passes (previously only `release_id`/`artist_id`/`playable_identity`) —
a modest, not measured-as-significant, I/O increase on the 220M-row credits scan.
`data/contracts/discogs-onehop-v1.md`'s frontier/retention definitions document both the
placeholder and role exclusions together. `packages/catalog/tests/test_onehop.py` gained
`test_pure_non_performer_role_excluded_from_frontier`, and the pre-existing
`test_frontier_retention_and_evidence` was updated: artist 21 ("Pat Producer," credited
only as "Producer, Engineer" in the synthetic fixture) no longer joins the frontier,
dropping the expected frontier count from 5 to 4 — a real behavior change to an existing,
previously-passing test, not a bug in the test.

## Validation

`make check` green (135 tests) after adding the role-filter test and updating the
pre-existing frontier test's expectations. The real `expand-one-hop` run was re-executed
after this fix; see `docs/BUILD_PLAN.md`'s Milestone 5 update and `docs/DATA_SIZING.md`
for the resulting real retained-release count.

## Revisit trigger

Revisit if a future real run still hits `--max-retained-releases` after both exclusions —
the next candidate is probably a per-role-*category* cap rather than a binary
eligible/excluded list, or reconsidering whether "producer" belongs on this list at all.
Revisit if `graph-core`'s traversal or `challenge.py`'s path-finding ever need the same
role-caliber notion for their own hop logic — today this filter is local to `onehop.py`'s
frontier/retention queries only, and duplicating the token list rather than sharing it
would be a real risk if that happens.
