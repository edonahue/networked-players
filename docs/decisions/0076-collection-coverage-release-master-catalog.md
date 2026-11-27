# ADR 0076: Collection coverage — owned release → master → catalog

- **Status:** Proposed (design only; nothing is implemented, ingested or published)
- **Date:** 2026-11-27
- **Builds on:** [ADR 0011](0011-private-seed-contract.md) (private seed contract),
  [ADR 0005](0005-discogs-hybrid-acquisition.md), [ADR 0006](0006-stream-discogs-gzip-to-parquet.md),
  [ADR 0038](0038-hybrid-album-catalog-assembly.md);
  `collection_candidates.py` (seed → masters for expansion supply)
- **Boundary:** [`docs/PUBLIC_PRIVATE_BOUNDARY.md`](../PUBLIC_PRIVATE_BOUNDARY.md)

## Context

A personal collection lists the *pressings* someone owns. The public catalog
(`catalog/albums.v1.json`) is keyed by **master** (`id = "master-<master_id>"`) and pins one
`main_release_id` per album. A duet-lab prototype that joined a collection export to the
published artifacts found that only a minority of owned records reached the catalog, and
most of those matched only by normalized artist + title — the owner has a different
pressing than the catalog's `main_release_id`. Title matching is fragile (remasters,
"Deluxe Edition", ANV vs. PAN artist names) and is not release-level evidence.

The release → master link already exists in data the project ingests: the monthly dump's
`releases` table carries `master_id` (`discogs/parquet.py` `RELEASE_SCHEMA`), and
`collection_candidates.py` already walks seed release ids → masters for the expansion
lane. Coverage reporting is the same walk, pointed at the published catalog.

## Decision (proposed)

A local-only `collection-coverage` diagnostic, composed from existing parts:

```text
SeedManifest (data/private/, release_ids only)            -- ADR 0011
  -> releases(release_id -> master_id) from the already-ingested monthly dump
  -> catalog albums.v1.json by master_id, then by main_release_id
  -> local/analysis/collection-coverage/<run>.json         -- never committed
```

1. **Input stays private.** The collection export is reduced to a `SeedManifest`
   (release ids only) by the existing `import-seed`; the export file and the seed stay in
   `data/private/` (git-ignored and agent-read-denied). Nothing reads account fields.
2. **Resolution uses the dump, not the API.** Look up `master_id` for the seed's release ids
   with one DuckDB query over the normalized `table=releases` Parquet of a snapshot that is
   already on the workstation/coordination host. This is a filtered read of bounded,
   checksummed partitions — no new dump download, no full-dump parse, and not a Pi job
   unless a pre-partitioned release-id slice is provided. No API calls (AGENTS.md).
   The one-hop corpus is *not* sufficient on its own: it holds only releases reached from
   frontier artists, so an owned release outside the frontier would falsely read as
   "no master".
3. **Match tiers, each labelled, never merged silently:**
   - `exact_release` — release id equals the album's `main_release_id`;
   - `same_master` — release's `master_id` equals the album's `master_id` (different
     pressing, same work) — the expected main win over title matching;
   - `no_master` — Discogs has no master for that release (singles, obscure pressings);
     reported, not guessed;
   - `title_match` (optional, flagged) — normalized PAN artist + title, used only to
     *suggest* a review, never counted as covered.
4. **Output is collection membership and therefore local-only**: written under `local/`,
   guarded the same way `collection_candidates`' CLI guards its output. Only aggregate
   method and schema are public; per-record results, counts tied to the owner, and example
   titles are not transcribed into public docs or PRs.
5. **Uncovered masters feed the existing expansion lane**, not the catalog directly:
   `derive_collection_candidates` and the owner's review (ADR 0031/0074) decide
   inclusion. Ownership never buys a catalog slot by itself.

## Consequences

Coverage becomes a reproducible, evidence-backed number instead of a title-match guess,
and the gap list is a ready input to the existing candidate pipeline. It depends on a
snapshot whose `releases` table is present locally; a snapshot mismatch (release merged or
deleted since) shows up as an unresolved id, reported with the snapshot version.

## Validation (when implemented)

Synthetic seed + synthetic `releases`/catalog fixtures covering each match tier, a null
`master_id`, a release absent from the snapshot, and a test that output refuses a path
outside `local/` and contains no non-release-id field from the export.

## Revisit trigger

Revisit if coverage needs per-pressing evidence (e.g. "your pressing's credits differ from
the catalog's main release") — that is a credit-level diff, a separate design.
