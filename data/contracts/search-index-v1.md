# Search index contract (search-index-v1)

The public site-search index
(`apps/web/public/data/search/index.v1.json`), produced by
`networked-players-catalog build-search-index` and validated by
`validate-search-index` /
`networked_players_contracts.search_index::search_index_failures`
(graph-expansion Phase 1, `docs/GRAPH_EXPANSION_DIRECTION.md` plan section 7).

> **Built entirely from two already-published artifacts, never a fresh
> corpus query.** The catalog and the contributor index -- the same
> discipline `contributor_index.py`'s own module docstring establishes for
> that artifact. This means the index can be rebuilt anywhere, including
> CI, with no dependency on the private one-hop working set.

## Why this exists

Before this artifact, "search" on this site meant `Array.includes` over
whatever array happened to already be loaded client-side (Connect's
combobox: the first 8 catalog-order substring matches, no ranking at all).
This gives every real destination -- every catalog album, every published
contributor -- one flat, rankable entry, consumed client-side by
`apps/web/src/game/siteSearch.ts`.

## Scope: Phase 1's own boundary, deliberately

Every entry's `state` is `"present"` in this artifact. `"candidate"`
entries (a known Discogs master by a catalog artist, not yet published --
plan section 4's "Known candidate" search state) need
`catalog/candidates.v1.json`, which needs the public `discogs-masters`
dataset cross-referenced against the catalog -- a Phase 3 deliverable this
builder has no dependency on. The `state` field already accepts either
value, so Phase 3 adding candidate entries needs no schema-version bump
here, only a build-time addition to `build_search_index`'s inputs.

## Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `entries[].kind` | `"album" \| "contributor"` | What kind of destination this entry is. |
| `entries[].id` | `string` | The catalog album id (`"master-<n>"`) or the contributor's `artist_id` as a string -- enough to build the destination URL (`/albums/<id>/` or `/contributors/<id>/`) client-side. |
| `entries[].label` | `string` | The album's title, or the contributor's name. |
| `entries[].sublabel` | `string \| null` | The album's artist name; `null` for a contributor (their name is already the label). |
| `entries[].state` | `"present" \| "candidate"` | Always `"present"` as of Phase 1 -- see "Scope" above. |

Tokenization/normalization (lowercasing, diacritic folding, prefix
matching) is deliberately NOT stored here -- `siteSearch.ts` normalizes
both the query and every entry's `label`/`sublabel` at query time. One
normalization implementation, applied when it's actually needed, rather
than duplicating it in two languages and bloating the artifact for a
search space this small (a few hundred entries).

## Real measured size (2026-09-03, real committed catalog and contributor
index)

179 albums + 530 contributors = 709 entries: 104,899 raw bytes, 12,071
gzip bytes -- both real byte counts of a public artifact's encoding, not
hardware performance data, published directly here per the same ADR 0018
precedent `pathfinding-graph-v4.md`'s own measured-effect table already
sets. Comfortably under the plan's own ≤150 KB gzip budget for the whole
search feature (index + `siteSearch.ts` combined).

## Validation

`search_index_failures(artifact, catalog, contributor_index)` checks:
exact top-level key set; `schema_version == 1`; every metadata string
non-empty; `catalog_version`/`contributor_index_version` agreement with
the supplied catalog/contributor index; every entry has the exact key set,
a valid `kind`, a non-empty `id`, a non-empty `label`, a `sublabel` that's
a string or null, and a valid `state`; no duplicate `(kind, id)` pairs;
every catalog album has exactly one entry and every contributor has
exactly one entry (an index missing coverage is a real defect, not a
silent gap); each album entry's `id` resolves in the catalog and each
contributor entry's `id` resolves in the contributor index;
`search_index_version` well-formed and recomputed from content.

## Status: real, committed, live

Built once against the real committed `catalog/albums.v1.json` and
`contributors/index.v1.json` (`search-index-v1-20260601-9d1888f0bded`),
registered as its own `search_index` group in `PUBLIC_ARTIFACT_GROUPS`,
`_artifact_validators()`, and `scripts/submit_artifact_check.py`'s
`_DEFAULT_ARTIFACTS`. Consumed by `siteSearch.ts`, wired into Connect's
album-picker combobox (replacing `filterAlbums`'s catalog-order substring
match) -- a header search on Explore/Browse pages (plan section 7's other
named consumer) is separate, later work, the same staged-publication
precedent every other Phase 1 slice has followed.

## Revisit trigger

When `catalog/candidates.v1.json` exists (Phase 3), extend
`build_search_index` to also emit `state: "candidate"` entries from it,
and extend `search_index_failures`'s coverage check accordingly (a
candidate entry has no catalog/contributor-index cross-check to run --
its own validator, once that artifact exists, is where its own `id`
gets checked). No schema-version bump needed for that addition alone.
