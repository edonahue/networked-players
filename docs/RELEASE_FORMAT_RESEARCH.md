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

## Candidate implementation options

### Option 1: Extend the monthly dump parser

Parse `<formats>` while streaming releases and retain a bounded normalized
`release_formats` table:

```text
snapshot_date
release_id
format_index
format_name
quantity
format_text
description_text
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

## Rights and operational boundary

The project should continue using monthly dumps for bulk processing. API
enrichment belongs in the private curator workflow, cached locally, with no
token in committed files, worker environments, or browser code. Public artifacts
should retain only the reviewed release and credit evidence allowed by the
project's public/private boundary.
