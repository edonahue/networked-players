# Discogs one-hop expansion dataset contract (v1)

This contract describes the one-hop corpus produced by `networked-players-catalog
expand-one-hop`, defined in
`packages/catalog/src/networked_players_catalog/discogs/onehop.py` (`expand_one_hop`).
It implements Milestone 5: seed release IDs → playable-artist frontier → retained
releases → an evidence-complete, versioned, immutable dataset.

> **Source of truth.** `onehop.py` is authoritative. If this document and the code
> disagree, the code wins and this file should be updated.

## Location and privacy

Output is written to `<output-root>/snapshot=<SOURCE_SNAPSHOT_DATE>/` (conventionally
`local/processed/discogs-onehop/snapshot=YYYYMMDD/`). **The entire dataset is
seed-derived and therefore private by location**: it lives only under the git-ignored
`local/` tree, exactly like the full parsed snapshot, and is never committed or
published. Committed tests use only synthetic seeds and fixtures. Public artifacts
derived from this corpus get their own contracts with their own leak rules.

## Expansion semantics

1. **Frontier** — every artist with a *playable* credit (`playable_identity`, i.e. a
   linked, positive Discogs artist ID) on any seed release present in the snapshot.
   Non-linked names never join the frontier.
2. **Retention** — every release in the snapshot with at least one playable credit by a
   frontier artist. Seed releases are necessarily retained (their own credits define the
   frontier). A non-linked name shared with a seed release never causes retention.
3. **Evidence completeness** — for every retained release, ALL of its credit rows are
   kept, including non-linked evidence rows, plus all of its track rows. No shortcut
   that drops evidence.

## Tables

Five `table=<name>/part-*.parquet` directories (zstd, level 6, row groups of 50,000):

| Table | Schema | Ordering |
| --- | --- | --- |
| `releases` | identical to `discogs-release-v2.md` releases | `release_id` |
| `tracks` | identical to `discogs-release-v2.md` tracks | all columns (content-deterministic) |
| `credits` | identical to `discogs-release-v2.md` credits | all columns (content-deterministic) |
| `frontier_artists` | single `artist_id` (int64) column | `artist_id` |
| `seed_releases` | single `release_id` (int64) column — seed IDs *present in the snapshot* | `release_id` |

Because the first three tables are schema-identical to a normal parsed snapshot, the
generic `networked-players-catalog validate` command works on this dataset unmodified.

## Determinism

Given the same seed manifest, source snapshot, and library versions, two runs produce
byte-identical parquet files (asserted by test): explicit `ORDER BY` per table makes row
order a pure function of row content.

## Manifest

`manifest.json` matches the parsed-snapshot manifest shape (`dataset_manifest_version`,
`schema_version`, `parser_version`, `counts`, `files` with per-file `sha256`), plus an
`expansion` block:

| Field | Meaning |
| --- | --- |
| `kind` | `"one-hop"` |
| `source_snapshot_date` / `source_manifest_sha256` | Which snapshot this expanded, verifiably |
| `seed_version` / `seed_release_count` / `seed_sha256` | Seed provenance **as aggregates only** — never the ID list, never a filesystem path |
| `frontier_artist_count` / `retained_release_count` | Expansion size |
| `seed_releases_missing_from_snapshot` | Seed IDs absent from the snapshot (non-fatal; possible when the collection is newer than the dump) |

## Guards

- Empty frontier → hard error, nothing written.
- `--max-retained-releases` exceeded → hard error **before** any table is written.
- Existing output without `--overwrite` → hard error (immutable by default).
- Self-check before the atomic rename: every seed release retained; every retained
  release provable by a playable frontier credit; zero orphan tracks/credits.
