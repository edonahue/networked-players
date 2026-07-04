# Graph snapshot contract (schema v1)

This contract describes the materialized co-credit adjacency dataset produced by
`networked-players-catalog export-graph-snapshot`, defined in
`packages/graph-core/src/networked_players_graph_core/snapshot.py`
(`GRAPH_SNAPSHOT_SCHEMA_VERSION`, `export_graph_snapshot`).

> **Source of truth.** `snapshot.py` is authoritative. If this document and the code
> disagree, the code wins and this file should be updated.

This is **not** a web artifact — see `challenge-v2.md` for the small, curated, public
challenge JSON. A graph snapshot is a full dump of every playable artist and every
co-credit edge within the traversal cap over a source dataset, typically the one-hop
working set. It exists so a future consumer (a larger web experience, offline
analysis, a different challenge generator) doesn't need to re-derive the adjacency
from raw credit rows every time.

## Privacy posture

When built from the one-hop dataset (the expected case), the output is seed-derived
and therefore **private by location**, the same posture as `discogs-onehop-v1.md`:
it belongs under git-ignored `local/processed/discogs-graph/snapshot=<X>/` and must
never be committed or published. This contract is public; the data it describes is
not.

## Generation method

Every table is built from the same identity and traversal rules as
`networked_players_graph_core.graph.CreditGraph`, reimplemented here as direct SQL
(not by opening a `CreditGraph`) so this exporter owns its own staging/atomic-write
discipline:

- A credit row counts only if `playable_identity` is true, `artist_id` is a positive
  integer, and `artist_id` is not one of the non-individual placeholder IDs (e.g.
  Discogs 194, "Various").
- A release drives edge generation only if it has between 2 and
  `max_artists_per_release` (default 50) distinct linked artists — releases with more
  are excluded from edge generation (but the artist rows themselves are unaffected).
  The cap value used is recorded in the manifest's `generation.max_artists_per_release`.

## Location

`<output-root>/snapshot=<YYYYMMDD>/`, zstd parquet, staging-dir + atomic-rename write,
manifest with per-file sha256 — the same dataset conventions as the release/one-hop
snapshots.

## `artists` table

| Column | Type | Meaning |
| --- | --- | --- |
| `artist_id` | int64 | Playable (linked) artist ID. |
| `name` | string | Canonical name — the most frequent `name` value across this artist's linked credits, never a one-off ANV. |

## `edges` table

One row per unordered co-credit pair (`artist_a_id < artist_b_id`, so each pair
appears exactly once).

| Column | Type | Meaning |
| --- | --- | --- |
| `artist_a_id` | int64 | Lower artist ID of the pair. |
| `artist_b_id` | int64 | Higher artist ID of the pair. |
| `release_ids` | list<int64> | Every traversal-eligible release both artists share a linked credit on, ascending. |
| `release_count` | int64 | `len(release_ids)` — the number of releases evidencing this edge. |

## Manifest provenance

Beyond the standard `dataset_manifest_version`/`schema_version`/`counts`/`files`
fields, the manifest carries a `generation` block:

| Field | Meaning |
| --- | --- |
| `method` | Human-readable description of the adjacency rule (see above). |
| `max_artists_per_release` | The cap value used for this export. |
| `source_manifest_sha256` | sha256 of the source dataset's own `manifest.json`, for provenance. |
| `source_expansion` | The source dataset's own `expansion` block passed through verbatim when present (i.e. when exporting from a one-hop dataset) — carries the one-hop's own seed-aggregate provenance one level further, never the seed IDs themselves. |

## Deliberately not included (v1)

Track-level co-credits (edges are release-artist-scope-equivalent, matching how
`CreditGraph`'s traversal treats any playable credit on a shared release — role text
and credit scope are not distinguished at the edge level; that detail remains in the
source credits table). Weighted/scored edges. Add via a schema-version bump when a
real consumer need appears.

## Validation

No dedicated `validate-graph-snapshot` command exists yet — `export_graph_snapshot`
refuses to write an empty `artists` table, and reuses the same staging + atomic
rename discipline as `expand-one-hop`/`write_release_dataset` so a failed export
never leaves a partial snapshot at the final path.
