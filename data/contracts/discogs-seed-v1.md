# Discogs private seed contract (schema v1)

This contract describes the private release-ID seed produced by `networked-players-catalog
import-seed`, defined in `packages/catalog/src/networked_players_catalog/discogs/seed.py`
(`SeedManifest`, `SEED_VERSION`).

> **Source of truth.** The `SeedManifest` dataclass in `seed.py` is authoritative. If this
> document and the code disagree, the code wins and this file should be updated.

## Location

The real seed is a single JSON file at `data/private/discogs-seed.json` — never committed.
`data/private/**` is git-ignored and denied to agent `Read` access at the tooling layer
(`.claude/settings.json`), in addition to `.gitignore`. Only synthetic seed fixtures
(`data/samples/discogs-collection-export.csv`) are tracked.

## `SeedManifest` — one JSON object

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `seed_version` | int | no | Schema version of this contract (currently 1). |
| `source` | string | no | Free-text label for the export mechanism. |
| `imported_at` | string (UTC ISO 8601) | no | When the import ran. |
| `release_ids` | array of int | no | Deduplicated, sorted Discogs release IDs. The entire seed. |

## Rules

- **Only `release_id` survives.** The import reads exactly one column from the source
  export and never accesses any other field. This is structural, not a post-hoc filter.
- **No account-linked fields, ever.** Nothing beyond a bare integer ID reaches the seed
  file or any derived artifact.
- **Never published.** The real seed lives only under git-ignored, agent-read-denied
  paths. The repository may publish this contract and synthetic examples, never a real seed.
- **Deduplicated and sorted.** For stable diffs and deterministic downstream processing.
- **Import is dataset-independent.** `import-seed` never checks whether a release ID
  exists in any parsed catalog dataset — that's Milestone 5's job, not this contract's.
