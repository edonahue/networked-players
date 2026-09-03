# Public album catalog contract (schema v1/v2)

This contract describes `apps/web/public/data/catalog/albums.v1.json` (ADR 0043), the
canonical, single source of truth for which albums exist across every real public surface
(album browser, Connection Guesser, Record Routes, Explore). Every one of those surfaces
derives its album set from this file's own `catalog_version`, never re-deriving or
narrowing it independently.

> **Source of truth.** `networked_players_graph_core.analysis::assemble_album_catalog` (the
> builder) and `validate_album_catalog`/`networked_players_contracts.catalog::public_album_catalog_failures`
> (the two byte-for-byte-agreeing validators) are authoritative. If this document and the
> code disagree, the code wins and this file should be updated. This document was written
> retroactively (graph-expansion Phase 0 slice 0-B, ADR 0069) against a catalog builder that
> already existed since ADR 0038/ADR 0043 -- it did not previously have a contract doc.

## Location

`apps/web/public/data/catalog/albums.v1.json`. Despite the filename's `v1`, the artifact's
**own** `catalog_schema_version` field (see below) is what actually distinguishes shape --
the filename never changes when the schema gains new, backward-compatible fields.

## Top-level fields

| Field | Type | Since | Meaning |
| --- | --- | --- | --- |
| `version` | int | v1 | Legacy, decorative field, always `1`. Not schema-version-aware; do not use it to detect v2 -- use `catalog_schema_version` instead. |
| `catalog_version` | string | v1 | Identity fingerprint: `catalog-v1-<snapshot_date>-<sha256[:12]>` over the sorted `artist_id:main_release_id:master_id:year` of every album. Changes if and only if the resolved album SET changes -- never on a presentation-only change (see `catalog_presentation_version`). |
| `snapshot_date` | string (`YYYYMMDD`) | v1 | The Discogs monthly-dump snapshot this catalog was resolved against. |
| `generated_by` | string | v1 | The CLI command + version that produced this artifact. |
| `source_note` | string | v1 | Human-readable provenance summary (which lanes/files fed the build). |
| `target_count` | int | v1 | The requested album count at build time. |
| `editorial_count` | int | v1 | How many albums came from the editorial backbone (`data/albums/top-albums-v1.json`). |
| `editorial_missed` | array | v1 | Editorial entries that failed to resolve, with reasons. |
| `pre_resolved_count` | int | v1 | Total albums across every pre-resolved lane (Buckets A/B/C -- personal seed, graph-rich, coverage-gap, already-published). |
| `pre_resolved_missed` | array | v1 | Pre-resolved entries that failed to resolve or collided, with reasons. |
| `pre_resolved_buckets` | array of `{label, count}` | v1 | Per-lane counts, in the order the lanes were processed. **Internal lane names**, not the public `selection_source` vocabulary -- e.g. Bucket A's internal label is `personal_editorial`, never renamed here (only the per-album v2 `selection_source` field and the inclusion audit normalize it to the public `editorial` label). |
| `candidate_count_considered` | int | v1 | How many `rank-album-candidates` shortlist entries were available. |
| `candidate_count_added` | int | v1 | How many generic candidates were actually added. |
| `albums` | array | v1 | The catalog itself -- see below. |
| `catalog_schema_version` | int, absent or `2` | v2 | Absent means v1 (no per-album v2 fields required). `2` means every album below carries `selection_source`/`featured`/`expansion_round`. Never any other value. |
| `catalog_presentation_version` | string | v2 (required when `catalog_schema_version` is present) | Sibling identity fingerprint: `catalog-presentation-v1-<snapshot_date>-<sha256[:12]>` over the sorted `id:featured:selection_source` of every album. Changes when a `featured` flip or a selection-source correction happens -- deliberately **never** shares a formula with `catalog_version`, so a presentation-only change never cascades the 11 other artifact groups that key off `catalog_version` (contributor index, evidence registry, pathfinding graph, games, ...). Read only by `apps/web` and the inclusion audit. |

## Per-album fields (`albums[]`)

| Field | Type | Since | Meaning |
| --- | --- | --- | --- |
| `id` | string | v1 | Stable album id (`master-<master_id>`), used in every URL and cross-artifact reference. Append-only across catalog growth -- never reassigned. |
| `artist_id` | int | v1 | PAN artist identity (never an ANV display string). |
| `artist` | string | v1 | Display name. |
| `master_id` | int or null | v1 | Discogs master id. |
| `main_release_id` | int | v1 | The release id this catalog entry cites as evidence -- see `master_eligibility.select_master_main_release_id` for how a v2-era build picks it (prefers the master's own canonical pressing; falls back to the earliest format-allowed pressing under the master when that pressing itself is a Reissue/Remastered edition the studio-album-v1 policy would reject). |
| `title` | string | v1 | Release title. |
| `year` | int | v1 | Original release year (the master's, not an edition date). |
| `selection_source` | string enum | v2 (required when `catalog_schema_version` is `2`) | Why this album is in the catalog: `editorial` (the top-albums-v1.json backbone, OR a personal-collection pick -- ADR 0069 decided both are publicly just "editorial," never a "personal_editorial"/"personal collection" label), `already_published` (preserved from an earlier round), `graph_rich` (algorithmic marginal-value pick), `coverage_gap` (algorithmic underrepresented-bucket pick), or `generic_candidate` (the proxy-ranking shortlist, unlabeled). |
| `featured` | bool | v2 (required when `catalog_schema_version` is `2`) | Resolved at build time from `data/albums/featured-v1.json`'s `master_id` pins (see that file). `true` means intentionally selected for prominent placement (may carry a blurb); `false` means a "graph record" -- an eligible, fully data-forward album that was never hand-featured. Never implies lower quality or hides the album from any listing. |
| `expansion_round` | int, >= 0 | v2 (required when `catalog_schema_version` is `2`) | Which expansion round added this album (`0` for the original catalog). **Known limitation:** a single `assemble_album_catalog` call applies one `expansion_round` value to every album it resolves in that call, including `already_published`-lane albums carried forward from an earlier round -- a future round that needs to preserve each already-published album's ORIGINAL round number must carry that as data on the preservation-lane input, not rely on this parameter. Not yet needed: no round beyond 0 exists yet. |

## Rules

- **`catalog_version` is identity-only, forever.** It hashes exactly `artist_id`,
  `main_release_id`, `master_id`, `year` -- never `selection_source`, `featured`,
  `expansion_round`, or any other presentation field. This is deliberate (ADR 0069): every
  one of the 11 downstream artifact groups that regenerate on a `catalog_version` change
  (contributor index, evidence registry, pathfinding graph, games, ...) must never be forced
  to rebuild just because an album's featured flag flipped.
- **v2 is additive and opt-in at the builder.** `assemble_album_catalog`'s
  `featured_master_ids` parameter gates whether v2 fields are produced at all; a caller that
  never passes it gets byte-for-byte today's v1 shape. The real committed
  `albums.v1.json` is v1-shaped as of this contract's writing (graph-expansion Phase 0 slice
  0-B) -- the code path to v2 has landed and is tested, but the artifact itself is not
  regenerated until Phase 1's `graph.v4` PR, per the graph-expansion plan's own phasing.
- **A v2 catalog is a strict superset of v1.** Every v1-only reader (the positional
  `pre_resolved_buckets` reconstruction in `catalog_audit.py`, anything reading only the
  common fields) keeps working unchanged against a v2 catalog.
- **`id` is append-only.** Growing the catalog must never reassign or reorder an existing
  album's `id`.
- **No private data.** No hostnames, file paths, collection membership, or any of the
  standard forbidden substrings/phrases (see `_CATALOG_FORBIDDEN_SUBSTRINGS`/
  `_CATALOG_FORBIDDEN_PHRASES` in `analysis.py`, mirrored in the contracts validator).

## Validators

- `networked_players_graph_core.analysis::validate_album_catalog` (raises
  `AlbumCatalogValidationError`).
- `networked_players_contracts.catalog::public_album_catalog_failures` (returns a failure
  list; the pure-Python, Pi-fleet-safe sibling with no `duckdb`/`lxml`/`pyarrow` dependency).

Both implementations must agree byte-for-byte on `_catalog_version` and
`_catalog_presentation_version` -- `test_catalog_contracts.py`'s cross-check tests assert
this directly against both v1 and v2 shapes.
