# Discogs masters dataset contract (schema v1)

This contract describes the parsed masters dataset produced by
`networked-players-catalog parse-masters`, defined in
`packages/catalog/src/networked_players_catalog/discogs/masters.py` (parser) and
`parquet.py` (`MASTERS_SCHEMA`, `MASTER_ARTISTS_SCHEMA`, `MASTER_SCHEMA_VERSION`).

> **Source of truth.** The PyArrow schemas in `parquet.py` are authoritative. If this
> document and the code disagree, the code wins and this file should be updated.

A **master** groups the release variants of one logical album/work; its
`main_release_id` is the release Discogs considers canonical for it. Masters are the
user-facing album identity for the public experience; release-level rows remain the
evidence layer (see `discogs-release-v2.md`).

## Location

`<output-root>/snapshot=<YYYYMMDD>/` (conventionally
`local/processed/discogs-masters/snapshot=<X>/`), zstd parquet, staging-dir +
atomic-rename write, manifest with per-file sha256 — the same dataset conventions as
the release snapshot.

## `masters` table

| Column | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `snapshot_date` | string | no | Source dump snapshot (YYYYMMDD). |
| `master_id` | int64 | no | Discogs master ID (the `id` attribute). |
| `main_release_id` | int64 | yes | The canonical release for this master. Always present in real observation (see `docs/discogs-data/raw-dump-schema.md`) but not treated as guaranteed. |
| `title` | string | yes | Master (album) title. |
| `year` | int32 | yes | Original year; `0`/non-positive normalized to null. |
| `genres` | list<string> | no (may be empty) | Document order preserved. |
| `styles` | list<string> | no (may be empty) | Document order preserved. |
| `data_quality` | string | yes | Discogs data-quality label. |
| `source_url` | string | no | Evidence URL of the source dump object. |

## `master_artists` table

Master-level artist credits, same identity rules as release credits: a linked positive
`artist_id` is the playable identity (PAN); `anv` is display text only; a missing/zero
ID is retained as evidence with `is_linked=false`, `playable_identity=false`, and never
becomes a playable identity.

| Column | Type | Null? |
| --- | --- | --- |
| `snapshot_date` | string | no |
| `master_id` | int64 | no |
| `artist_id` | int64 | yes |
| `name` | string | yes |
| `anv` | string | yes |
| `join_text` | string | yes |
| `is_linked` | bool | no |
| `playable_identity` | bool | no |

## Deliberately not parsed (v1)

`videos` (presentation, not evidence), and any field not listed above. Add via a
schema-version bump when a real need appears, not speculatively.

## Validation

`networked-players-catalog validate-masters --dataset <root>`: hard failures on
orphan `master_artists` rows, linked credits with invalid IDs, duplicate `master_id`s,
and manifest count mismatches; `masters_missing_main_release` is reported as a metric,
not failed on.
