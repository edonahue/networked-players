# ADR 0029: Connectivity scorer flags the CreditGraph/onehop.py exclusion gap, doesn't fix it at the source

- **Status:** Accepted
- **Date:** 2026-07-05

## Context

Building the cohort connectivity scorer (`cohort_connectivity.py`, PR 3 of the curated-
cohort pipeline) surfaced a real, previously-unaddressed gap: [ADR 0026](0026-exclude-placeholder-artists-from-one-hop-frontier.md)
and [ADR 0027](0027-exclude-non-performer-roles-from-one-hop-frontier.md) exclude two
Discogs placeholder identities ("Various Artists" 194, "Trad." 151641) and pure
non-performer-role credits (Written-By, Mastered By, Producer, etc.) from the one-hop
dataset's *frontier and retention* logic — but those exclusions live entirely inside
`packages/catalog/.../discogs/onehop.py`'s SQL, which only runs once, when the one-hop
dataset itself is built.

`CreditGraph` (`packages/graph-core/.../graph.py`), the traversal engine both
`challenge.py` and this new connectivity scorer use, is a completely separate code path
with its own, narrower exclusion: `NON_INDIVIDUAL_ARTIST_IDS = frozenset({194})`. It does
not know about 151641, and it does not filter by role at all. Because the one-hop
dataset's own evidence-completeness rule keeps *every* credit row of a retained release
(not just the ones that justified retention), a release legitimately retained via a real
performer credit can still carry a "Trad." credit or a Mastered-By-only credit as
evidence — and `CreditGraph.find_path`'s BFS will happily traverse through it if it
connects two artists, producing exactly the kind of weak, noisy connection ADR 0026/0027
were written to prevent, just one layer downstream of where those ADRs actually apply.

## Decision

The connectivity scorer catches this **post-hoc, by flagging**, not by changing
`CreditGraph`'s own traversal filters. Every hop in a found path is classified via
`classify_hop_quality()`, which duplicates `_PLACEHOLDER_ARTIST_IDS` (`{194, 151641}`) and
`_NON_PERFORMER_ROLE_TOKENS` as graph-core's own copy (the same "kept as our own copy per
the no-reverse-dependency rule" precedent `graph.py`'s own `NON_INDIVIDUAL_ARTIST_IDS`
already establishes — graph-core must never import from `networked_players_catalog`).
A hop through a placeholder identity or a non-performer-only credit gets a
`quality_flags` entry (`placeholder_artist_hop`, `non_performer_only`) and a
human-readable `warnings` string; it is never silently dropped, and never auto-excluded
from the artifact.

**Explicitly not done**: extending `CreditGraph.NON_INDIVIDUAL_ARTIST_IDS` or adding
role-based filtering to `linked_credits`/`find_path` itself. That would be the more
"thorough" fix, but it would silently change `challenge.py`'s existing, already-live
traversal behavior (the album-centered web experience) as a side effect of fixing a
cohort-pipeline concern — a bigger, riskier, cross-cutting change than this PR's scope
justifies, and one neither `challenge.py`'s own tests nor this session's review were
built to validate.

## Consequences

`data/contracts/album-cohort-connectivity-v1.md` documents the flag taxonomy and the gap
it exists to catch. `review-report.md` surfaces flagged pairs for human review before
anything is considered genuinely playable. `challenge.py`'s existing behavior is
completely unaffected — this PR touches no shared traversal code. The duplicated constant
sets (`_PLACEHOLDER_ARTIST_IDS`, `_NON_PERFORMER_ROLE_TOKENS`) now exist in three places
(`onehop.py`, and now `cohort_connectivity.py`'s own copy, following `graph.py`'s existing
one-place duplication) — a real, accepted maintenance cost of the no-reverse-dependency
rule, not a new problem this ADR introduces.

## Validation

`make check` green with the new module's tests, including a synthetic-dataset test
proving a hop through artist 151641 gets `placeholder_artist_hop` (fixture artist 194
can't be used for this specific test, since `CreditGraph` already excludes it from
traversal entirely — 151641 is the one that actually demonstrates the gap) and a synthetic
test proving a hop connected only via non-performer-role credits gets `non_performer_only`.

A real smoke test against the real one-hop dataset **confirmed a related, previously
only-hypothetical performance risk is real, not just theoretical**: `CreditGraph.open()`
and `stats()` both complete quickly, but a `score_pairs` run touching even a small number
of resolved albums can hang for a long time if any of them is connected to a real,
legitimately-prolific hub artist (a heavily-covered songwriter or prolific engineer —
exactly the class of connection ADR 0026/0027 deliberately did *not* exclude, since those
are real people with real credits, not placeholders). The smoke test was killed rather
than left to complete; no real timing number is recorded here per ADR 0018's convention.
This does not block PR 3 — the scorer's job is to compute and flag, not to be fast — but
it sharpens the revisit trigger below from "if it's slow" to "it already is, for some
real cohort compositions."

## Revisit trigger

**Now confirmed, not just anticipated**: revisit `find_path`'s per-pair performance
(the `graph-snapshot-v1` in-memory-adjacency approach floated in this PR's planning is
the leading candidate) before this scorer is run against a real, larger cohort in
production — a real smoke test already hit multi-minute-plus hangs on a small cohort that
happened to touch a hub-connected artist. This is now a near-term follow-up, not a
someday-maybe.

Revisit fixing this at the traversal layer (extending `CreditGraph`'s own filters to match
`onehop.py`'s) only if flagged pairs turn out to be very common in practice on a real
cohort — at that point, flagging becomes a annoyance rather than a safety net, and a
shared, tested exclusion definition used by both `onehop.py` and `graph.py` would be
worth the cross-cutting risk. Revisit the duplicated-constants maintenance cost if a
fourth copy is ever needed — that would be the signal to extract a small shared
definition, carefully, given the no-reverse-dependency constraint still has to be
satisfied somehow (e.g. a new leaf package both `catalog` and `graph-core` can depend on).
