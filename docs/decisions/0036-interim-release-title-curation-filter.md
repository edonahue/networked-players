# ADR 0036: Interim title filter for compilation-like evidence releases

- **Status:** Accepted, interim
- **Date:** 2026-07-11
- **Extends:** [ADR 0035](0035-track-scoped-credit-edges.md)

## Context

ADR 0035 removed release-container cliques and added track-scoped edges, but the
normalized snapshot does not retain Discogs release format descriptions. A
small compilation, sampler, bootleg, or greatest-hits release can therefore
still look album-shaped when it has only a few credited track artists.

The rebuilt cohort exposed the residual clearly: 675 evidence hops covered 296
distinct releases, and 163 hops across 59 releases had obvious title signals
such as `Bootlegs`, `Greatest Hits`, `Sampler`, `Collection`, `Live`, `MashUp`,
or `Remix`.

## Decision

As an interim first-cohort guard, `credit_edges` excludes releases whose title
contains an explicit compilation-like signal:

`compilation`, `sampler`, `greatest hits`, `best of`, `anthology`, `collection`,
`rarities`, `bootleg`, `mashup`, `live`, `remix`, `reissue`, `soundtrack`,
`singles`, or `box set`.

This is applied at the graph edge boundary, so it removes bad intermediary
evidence as well as bad endpoints. It does not delete source rows, alter the
raw or normalized catalog, or claim that a title is a reliable release-type
classifier. Track-level guards from ADR 0035 remain active.

## Why this is temporary

Discogs treats format as structured release data: the format has a main type,
quantity, descriptions, and free-text format notes. The Discogs guidelines also
distinguish Album, Mini-Album, EP, Single, and compilation-like releases when
describing master-release membership. See:

- [Discogs Database Guidelines: Format](https://support.discogs.com/hc/en-us/articles/360005006654-Database-Guidelines-6-Format)
- [Discogs Database Guidelines: Master Release](https://support.discogs.com/hc/en-us/articles/360005055493-Database-Guidelines-16-Master-Release)
- [Discogs Database Guidelines: Title](https://support.discogs.com/hc/en-us/articles/360005054813-Database-Guidelines-3-Title)

Titles alone create both false positives and false negatives. For example,
`Volume 4` may be a studio album, while a release with no title signal may be
a sampler. The filter should be removed or reduced once structured format data
is available.

## Comprehensive research direction

The durable design is a release-format policy, separate from graph traversal:

1. Preserve normalized format rows from the monthly dump's `<formats>` element,
   including main format, quantity, descriptions, and free-text text.
2. Add a versioned `release_shape` or `release_format_policy` projection with
   explicit values such as `studio_album`, `live_album`, `compilation`,
   `sampler`, `single`, `ep`, `soundtrack`, `bootleg`, `remix`, and `unknown`.
3. Keep the raw format evidence and source snapshot on each classification.
4. Make the cohort scorer accept a named policy, initially
   `studio-album-evidence-v1`, rather than embedding title rules in SQL.
5. Treat `unknown` as review-required, not automatically eligible.
6. Measure recall against a synthetic fixture matrix and a manually reviewed
   sample of real evidence releases before changing the public cohort.

The API can enrich selected releases because Discogs API content includes
format, track listings, and credits, but API calls should remain an operator
or curation aid, not a bulk-ingestion dependency. The project continues to use
monthly dumps for bulk catalog work.

## Consequences

- The first cohort becomes more conservative immediately.
- Some legitimate live albums, remix albums, soundtrack releases, and albums
  with unfortunate titles will be excluded until a human can review them.
- Existing graph and scorer counts will change; scorer versioning and a fresh
  local rebuild are required.
- The title pattern must remain visible, tested, and easy to retire.

## Validation

The synthetic graph tests cover both an explicit live B-side and an otherwise
album-shaped `Greatest Hits` release. The next real rebuild should report the
count of title-filtered evidence releases so the interim guard can be measured
against the eventual format-aware policy.
