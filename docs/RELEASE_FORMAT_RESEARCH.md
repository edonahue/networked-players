# Release Format Research

This note records the research behind the interim compilation filter in
[ADR 0036](decisions/0036-interim-release-title-curation-filter.md).

## Current finding

The normalized one-hop snapshot preserves release title, credits, and tracks,
but not the source release's structured `<formats>` data. That makes it
impossible to distinguish a studio album from a sampler or a compilation with
high confidence using the current tables alone. Title heuristics are useful as
an emergency guard, but they are not a durable classifier.

## Discogs evidence model

Discogs documents format as structured release information: a release may have
a main format, quantity, descriptions, and free-text format text. The official
guidelines distinguish Album, Mini-Album, EP, Single, and related format
descriptions. See the [Format guidelines](https://support.discogs.com/hc/en-us/articles/360005006654-Database-Guidelines-6-Format).

Discogs master releases group related versions; they do not replace the
release-level format facts. The master-release guidance explicitly discusses
Album, EP, Single, remix, promo, and sampler distinctions. See the [Master
Release guidelines](https://support.discogs.com/hc/en-us/articles/360005055493-Database-Guidelines-16-Master-Release).

The title itself is user-entered release data. Discogs specifically advises
that a single or two-track release can use the main track title, which is why
title-only classification cannot reliably detect singles. See the [Title
guidelines](https://support.discogs.com/hc/en-us/articles/360005054813-Database-Guidelines-3-Title).

## Structured dump mapping

The streaming parser preserves each `<formats><format>` row in the normalized
`release_formats` table. `name`, `qty`, and `text` map to `format_name`,
`quantity`, and `format_text`; nested `<description>` values remain an ordered
list. This keeps the distinction between a carrier (`LP`, `Vinyl`, `CD`) and
descriptors (`Album`, `Compilation`, `Sampler`, and so on).

## Candidate implementation options

### Option 1: Extend the monthly dump parser

Parse `<formats>` while streaming releases and retain a bounded normalized
`release_formats` table. This is now the implemented foundation:

```text
snapshot_date
release_id
format_index
format_name
quantity
format_text
   descriptions
source_snapshot
parser_version
```

Advantages: complete bulk coverage, reproducibility, no API rate-limit or token
dependency, and direct provenance. This is the recommended long-term path.

### Option 2: Enrich only candidate evidence releases through the API

Fetch format metadata for the few hundred releases in a local editorial packet,
cache the responses privately, and attach a review-only classification. This is
useful for immediate curation and image/evidence work, but it cannot replace
bulk normalization and should never distribute the API token to workers or the
browser.

### Option 3: Infer from title, track count, and credit shape

This is the current interim approach. It is cheap and deterministic but has
known false positives and false negatives. It should remain a temporary
fallback only, with an explicit `unknown` outcome rather than silent confidence.

## Current policy model

`studio-album-v1` requires an explicit `Album` descriptor. `Compilation`,
`Sampler`, `Single`, `Maxi-Single`, `EP`, `Mini-Album`, `Mixtape`, `Live`,
`Bootleg`, `Unofficial Release`, `Remix`, `Soundtrack`, or `Box Set` descriptors
exclude automatic eligibility. Missing or conflicting data is reviewable. An
explicit `Compilation` wins even when `Album` is also present. Reissue and
remaster descriptors do not disqualify an explicit Album.

## Recommended policy model

Keep traversal semantics and editorial release policy separate. A future
`release_format_policy` should classify evidence releases with a decision and
reason list:

```text
decision: allow | exclude | review
shape: studio_album | live | compilation | sampler | single | ep | soundtrack | remix | unknown
signals: [format_name, description, title, master_relationship, ...]
source_snapshot
parser_version
```

For the first public cohort, allow only `studio_album` evidence by default;
send `unknown`, `live`, and ambiguous multi-format releases to human review.
Do not infer artistic influence from a format or shared credit.

## Validation plan

Build a synthetic matrix covering:

- studio album with producer and guest credits;
- single with a live B-side;
- compilation with two, four, and many track artists;
- sampler with a misleading album-like title;
- live album with no title signal;
- reissue and deluxe edition;
- soundtrack with an individual billed artist;
- unknown/malformed format data.

For a real snapshot, measure:

- evidence releases excluded by each format rule;
- evidence releases sent to review;
- endpoint pairs lost versus the title-only policy;
- repeated intermediaries before and after filtering;
- manually judged false-positive and false-negative rates.

## Validation results (observed, 2026-07-19, snapshot 20260601)

The synthetic matrix above is now executed as `packages/catalog/tests/test_release_format_policy.py`
(one test per bullet). Two matrix cases are not inputs to `classify_formats` at all and are
covered elsewhere instead: "compilation with two/four/many track artists" is
`album_shaped()`/`COMPILATION_TRACK_ARTIST_THRESHOLD` in `graph.py` (a traversal-layer guard,
already tested there); "soundtrack with an individual billed artist" and "studio album with
producer and guest credits" are about credit shape, not format data, and belong to the
`credit_edges`/eligibility layer instead.

Real-snapshot measurement ran `classify-release-formats` against the format-enriched one-hop
dataset (`discogs-onehop-v3`, 1,410,106 releases) and `compare-release-format-policy` against
the legacy title-only guard. Observed, from a real run (not projected):

| Metric | Count |
| --- | --- |
| Releases classified | 1,410,106 |
| `allow` (before the title safety net below) | 693,113 |
| `exclude` | 600,373 |
| `review` (before) | 116,620 |
| Disagreements vs. the legacy title-only filter | 536,308 |
| ...of which the format policy correctly caught what titles missed | 502,379 |
| ...of which titles flagged something the format policy allowed | 33,929 |

**A manually judged sample of the 33,929 "titles flagged, format policy allowed" releases found
a real, measured false-positive pattern, not evenly distributed noise**: stratified regex
matching over the full 33,929 (not just the sample) found 32,119 (94.7%) contained "live",
"bootleg", or "soundtrack" in the title (e.g. real titles observed: "801 Live", "Unplugged (The
Official Bootleg)", "Live In Japan", "Live Cream Volume II", "Apollo - Atmospheres &
Soundtracks") while their only structured format descriptor was a bare `Album` — Discogs
contributors evidently tag carrier/edition facts (LP, CD, Reissue, Mono, Stereo) far more
consistently than the `Live`/`Soundtrack` descriptor itself. Only 6 of the 33,929 were
reissue-only matches (the correct, intended override — reissue must not disqualify an explicit
Album — confirmed working as designed).

**Fix applied** (`classify_formats`, `packages/catalog/.../release_format_policy.py`): an
optional `title` parameter and a narrow `_RESIDUAL_LIVE_SIGNAL_PATTERN`
(`bootlegs?|live(?:box)?|soundtracks?|sound collages?` — deliberately narrower than the legacy
`_TITLE_SIGNAL_PATTERN`, excluding "reissue" and the broader compilation-family terms) that can
only **downgrade** an `allow` to `review`, never exclude and never promote — the same
"can only under-filter" precedent as ADR 0027/0036's own keyword guards. This is exactly the
`title` signal the "Recommended policy model" section above already anticipated, now
implemented as a bounded safety net rather than a parallel classifier.

Re-running with the fix: `allow` 693,113 → 660,994 (-32,119, matching the measured gap exactly),
`review` 116,620 → 148,739 (+32,119), `exclude` unchanged at 600,373. Re-running the shadow
report: `title_filtered_format_allowed` disagreements 33,929 → 1,810 (-94.7%).

**Manually judged, the residual 1,810 are a distinct, smaller, already-understood category**: a
sample showed titles like "Greatest Hits", "Anthology 3", "The Best Of Freddy McKay" — real
compilations Discogs tagged only `Album` (missing `Compilation`), not live/bootleg/soundtrack
titles. Deliberately **not** added to the safety net in this pass: "greatest hits"/"anthology"/
"best of"/"collection" are higher-collision keywords (a real studio album titled "Collection" or
"Anthology" is plausible) than "live"/"bootleg"/"soundtrack", and compilations are already the
best-covered exclude category structurally (380,004 of 600,373 excludes). Flagged here as a
known, quantified, deferred residual rather than silently left unmeasured.

**Deferred to the PR3 cohort re-score** (a natural byproduct of that required diff, not
re-measured separately here): endpoint pairs lost versus the title-only policy, and repeated
intermediaries before/after filtering — both require an actual connectivity re-scoring run,
which PR3 performs anyway once `scripts/submit_cohort_score.py` carries the format-policy fix.

Artifacts from this run: `local/analysis/release-format-policy-v2/{release-format-policy,
release-format-scoring-index,format-policy-shadow}.json` (local-only, not committed, per this
project's benchmark/analysis-results-stay-local convention — ADR 0018's same posture applied to
a format-policy measurement rather than a performance benchmark). The prior 2026-07-11 run
under `local/analysis/cohorts/discogs-community-best-albums/` predates this fix and should not
be treated as current; PR2/PR3 album and round generation should use the `-v2` scoring index.

## Rights and operational boundary

The project should continue using monthly dumps for bulk processing. API
enrichment belongs in the private curator workflow, cached locally, with no
token in committed files, worker environments, or browser code. Public artifacts
should retain only the reviewed release and credit evidence allowed by the
project's public/private boundary.

## Bounded Pi work

The Raspberry Pi fleet could perform bounded API enrichment, but the current
project boundary intentionally does not distribute credentials to workers. The
safe future opt-in is a node-local secret injected outside Git (for example via
Ansible or a Swarm secret), a private allowlisted release-ID queue, strict rate
and concurrency limits, and master-side acceptance of returned metadata. Pis
could then fetch only assigned releases, validate image URLs and response shape,
normalize metadata into a small checksummed sidecar, detect missing or changed
fields, and return bounded diagnostics. They must not crawl arbitrary URLs,
publish API responses, or replace dump-derived facts. Enabling this would be an
explicit security/operations ADR change, not an incidental part of dump parsing
or graph scoring.
