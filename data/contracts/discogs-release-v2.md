# Discogs release dataset contract (schema v2)

This documents the normalized Parquet tables produced by `parse-releases` in the
[catalog package](../../packages/catalog/README.md). It corresponds to
`SCHEMA_VERSION = 2` in
`packages/catalog/src/networked_players_catalog/discogs/parquet.py`.

> **Source of truth.** The PyArrow schemas in `parquet.py` (`RELEASE_SCHEMA`,
> `TRACK_SCHEMA`, `CREDIT_SCHEMA`) are authoritative. This file tracks them for human and
> agent readers; if they disagree, the code wins and this file should be updated.

A dataset lives at `…/snapshot=<YYYYMMDD>/` with one subdirectory per table
(`table=releases/`, `table=tracks/`, `table=credits/`) plus a `manifest.json` recording
schema version, row counts, and per-file bytes/hashes. Every row carries `snapshot_date`
so tables remain self-describing once separated from their path.

## `releases` — one row per release

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `snapshot_date` | string | no | Source dump snapshot, `YYYYMMDD` |
| `release_id` | int64 | no | Stable Discogs release id |
| `status` | string | yes | Release status (e.g. `Accepted`) |
| `title` | string | yes | Release title |
| `country` | string | yes | Release country |
| `released` | string | yes | Release date or year, as given (e.g. `2001`, `2003-04-01`) |
| `master_id` | int64 | yes | Master id when present |
| `master_is_main_release` | bool | no | Whether this release is the master's main release; `false` when `master_id` is absent (real full-dataset check, 2026-07-02: never actually null — see `docs/discogs-data/raw-dump-schema.md`'s "Real full-dataset profiling") |
| `data_quality` | string | yes | Discogs data-quality label (e.g. `Correct`, `Needs Vote`) |
| `source_url` | string | no | Provenance: the dump object URL |

## `tracks` — one row per ordered track or subtrack

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `snapshot_date` | string | no | Source dump snapshot |
| `release_id` | int64 | no | Owning release |
| `track_index` | int32 | no | Flat 0-based traversal index |
| `parent_track_index` | int32 | yes | `track_index` of the parent for subtracks; null at top level |
| `track_path` | string | no | Hierarchy path, e.g. `0`, `1`, `1.0` |
| `position` | string | yes | Original position text (e.g. `A1`, `A2a`) |
| `title` | string | yes | Track title |
| `duration` | string | yes | Duration text (e.g. `3:15`) |

## `credits` — one row per release- or track-level artist/credit

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `snapshot_date` | string | no | Source dump snapshot |
| `release_id` | int64 | no | Owning release |
| `track_index` | int32 | yes | Owning track for track-scope credits; null for release-scope |
| `track_path` | string | yes | Track hierarchy path for track-scope credits; null otherwise |
| `track_position` | string | yes | Track position text for track-scope credits; null otherwise |
| `track_title` | string | yes | Track title for track-scope credits; null otherwise |
| `credit_scope` | string | no | One of `release_artist`, `release_credit`, `track_artist`, `track_credit` |
| `artist_id` | int64 | yes | Discogs linked artist id (**PAN**); null when not linked |
| `name` | string | no | Credited name as given in the source |
| `anv` | string | yes | Artist Name Variation — display override, kept separate from `artist_id` |
| `join_text` | string | yes | Connector text between artists (e.g. `&`) |
| `role_text` | string | yes | Original, un-normalized role text (e.g. `Producer, Engineer`) |
| `credited_tracks_text` | string | yes | Track(s) a credit applies to, when scoped (e.g. `A2`) |
| `is_linked` | bool | no | True when `artist_id` resolves to a linked artist (`> 0`) |
| `playable_identity` | bool | no | True only for linked artists eligible to be graph nodes |

### Identity and evidence rules

- **PAN ≠ ANV.** `artist_id` (the persistent artist id) is the identity key; `anv` is
  display text only. Never collapse them.
- **Non-linked names are evidence, not identities.** A credit with `artist_id` null /
  `is_linked = false` is retained as evidence but `playable_identity` is false — it must not
  become a graph node until a documented resolution exists.
- **Scope is preserved.** Release-scope and track-scope credits are distinct rows; the four
  `credit_scope` values are not interchangeable.
- **Original role text is preserved** before any later normalization.
- **Edges mean co-credit, never influence.** Two artists sharing a release/track is
  documented collaboration only.
