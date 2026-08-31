# Album-hop-distances contract (album-hop-distances-v1)

The public album-hop-distances artifact
(`apps/web/public/data/contributors/album-hop-distances.v1.json`), produced
by `networked-players-catalog build-album-hop-distances` and validated by
`validate-album-hop-distances` /
`networked_players_contracts.album_hop_distances::album_hop_distances_failures`
(ADR 0048 addendum).

> **A companion artifact to `contributor-index-v1`, deliberately not a
> field on it.** `contributor-index-v1`'s contract is validated as an exact
> top-level key set on every `contributors[]` entry. Adding a new required
> key there would reject every already-published v1 file under old
> validator code, and would itself be rejected by any external consumer
> pinned to the documented v1 key list — a real breaking change hiding
> behind an unchanged `schema_version`. This artifact instead carries the
> `hop_distance` data separately, the same pattern ADR 0058's
> evidence-release-registry already established alongside
> `contributor-index-v1`: a small, independently versioned artifact rather
> than a widened existing one.

## Top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1`. |
| `catalog_version` | string | The canonical `catalog/albums.v1.json` version this artifact belongs to. |
| `album_hop_distances_version` | string | `album-hop-distances-v1-<snapshot>-<hash>` — a content hash of every entry, sorted by `(artist_id, album_id)` (order-INSENSITIVE). |
| `generated_at` | string | Explicit operator-supplied ISO datetime (never the wall clock). |
| `source` | string | Provenance note naming the source artifacts. |
| `license` | string | See `docs/DATA_AND_RIGHTS.md`. |
| `entries` | array | See below. May be empty. |

## `entries[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `artist_id` | int | The Discogs PAN artist id. Must be a real `artist_id` in the companion `contributor-index-v1` artifact. |
| `album_id` | string | A canonical catalog album id (must exist in the catalog). |
| `hop_distance` | int | The minimum number of documented credit-hops from this artist's nearest occurrence in any `challenge.v2.json` path or `routes/rounds.v1.json` round to this endpoint album. `0` means the artist is directly adjacent to that album's representative artist (the common case, e.g. every artist is `0` hops from their own album); any value greater than zero — including `1` — means a real but more distant documented chain, never a claim of a direct credit on that album's own release. Frontend copy must surface this whenever `hop_distance !== 0`. |

`entries` is sorted by `(artist_id, hop_distance, album_id)` and contains no
duplicate `(artist_id, album_id)` pair.

## Validation

`album_hop_distances_failures(artifact, catalog, contributor_index)`
checks: exact top-level key set, `schema_version == 1`, `catalog_version`
agreement with the canonical catalog, `album_hop_distances_version`
recomputation, every entry having exactly the three required keys with the
correct types (`artist_id` a real contributor in `contributor_index`,
`album_id` resolving against the catalog, `hop_distance` a non-negative
integer), no duplicate `(artist_id, album_id)` pair, and the array sorted by
`(artist_id, hop_distance, album_id)`. A malformed `album_id` (e.g. a list
or object from corrupt JSON) is reported as a contract failure, never
allowed to crash validation via an unguarded set/dict operation.

## Revisit trigger

If a future surface needs hop-distance data scoped beyond
`challenge.v2.json`/`routes/rounds.v1.json` (the same two artifacts
`contributor-index-v1` is built from), extend those two source artifacts
first, or add a clearly-named `v2` artifact with its own version namespace —
never silently widen `album-hop-distances-v1`, and never fold this data back
onto `contributor-index-v1` itself.
