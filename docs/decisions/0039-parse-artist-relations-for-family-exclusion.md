# ADR 0039: Parse real Discogs group/member relations instead of hand-curating an exclusion list

- **Status:** Accepted
- **Date:** 2026-07-19

## Context

The game must not present a group and its own frontperson (e.g. a band and its lead
singer's solo act) as an interesting "connection" — the shared credit is trivial, not
a discovery. The operator's brief called for this exclusion to be "auditable,
deterministic" and explicitly rejected inferring relationships from a shared credit
or from name-string resemblance (the same risk this launch already found and fixed
once, in album-candidate resolution — matching on `artist_id`, never on name text).

The fallback originally anticipated for this was a hand-reviewed candidate list,
written on the assumption that no structured group/member data existed in this
project. `docs/discogs-data/raw-dump-schema.md` documents otherwise:
`artists.xml.gz` carries real, numeric-ID `<members>`/`<groups>` tags — Discogs'
own editorial linkage between a group act and its individual members — and the
project had never parsed them (confirmed: "not parsed by this project at all").
Real structured data was available and unused; a hand-curated list would have been
a strictly worse source of truth for the same problem.

## Decision

Add a small, focused parser (`packages/catalog/.../discogs/artists.py`) that streams
`artists.xml.gz` once, using the same proven gzip-streaming/iterparse pattern
`parse-releases` already uses, extracting only `<groups>`/`<members>` relations —
not the rest of the artist record. Output is a normalized `artist_relations` Parquet
table (`ARTIST_RELATIONS_SCHEMA`), one row per (person, group) pair, real and
unfiltered, for the full artist universe.

That table is never published directly — it's a 4,688,536-row, 10,081,427-artist-scan
intermediate, out of scope for public release on its own. A second function,
`build_artist_family_exclusions` (`discogs/artist_family.py`), narrows it to a small,
committed, **scoped** artifact: it only emits `person_id` entries for artist IDs
already in the launch's own bounded universe (round endpoints and bridges, at most a
few hundred IDs), publishing only `person_id -> group_act_ids[]`. Real launch
measurement: 59 scoped entries.

Discogs' `<groups>`/`<members>` tags are not guaranteed to be mirrored in both
directions on every record (a member might list the group without the group's own
record listing that member, or vice versa), so `build_artist_family_exclusions`
unions both directions — a one-sided mirror still produces the relationship.

`is_family_excluded_pair` consumes this artifact to reject a candidate round whose
endpoints are a group and one of its own members, before that round ever reaches
generation. This sits alongside, and independent of, ADR 0038's performer-role
allowlist — a real instrument/vocal credit can still be excluded here if it's
between a group and its own frontperson.

## Consequences

- The exclusion is fully auditable: every entry traces to a real Discogs
  `<members>`/`<groups>` tag on a specific artist record, not to a heuristic or a
  human's private judgment call. A human spot-check pass over the small scoped list
  remains cheap and valuable, and is exactly what the small size enables.
- No hand-curated list needs maintaining as new albums enter the catalog — re-running
  `parse-artist-relations` plus `build-artist-family-exclusions` against the current
  launch's artist universe keeps the exclusion current for free.
- The full 4.7M-row `artist_relations` table stays local-only (it is bulk Discogs
  editorial data, not itself privacy-sensitive, but out of scope to publish under
  this launch and not needed beyond the scoped artifact it produces).
- This does not attempt to model looser affiliations (a touring member, a
  session-only credit, a side project) — only Discogs' own explicit group/member
  linkage. That is a deliberate, narrow scope match to "auditable, deterministic,"
  not a claim of completeness.

## Validation

`packages/catalog/tests/test_artists.py` covers the streaming parser (group/member
extraction, bounded early termination, malformed-input failure, Parquet round-trip)
mirroring `test_releases.py`'s established coverage shape for `parse-releases`.
`packages/catalog/tests/test_artist_family.py` covers both-direction union, scoping
(an artist outside the requested ID set never appears), and
`is_family_excluded_pair`'s exclusion behavior.

## Revisit trigger

If a future cohort/game surface needs the full, unscoped `artist_relations` table
rather than a per-launch scoped exclusion artifact, that is a real product decision
to publish more than this ADR's scope currently allows — the parser already produces
the full table locally, so nothing needs re-parsing, only a new publication decision.
Revisit the "explicit tags only" scope if Discogs data shows this genuinely misses
frontperson pairs that should be excluded (visible as a game round pairing an
obvious group and its own singer that this artifact didn't catch).
