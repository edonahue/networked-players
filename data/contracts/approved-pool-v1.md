# Contract: approved album pool v1

`data/albums/approved-pool-v1.json` — the cumulative, committed list of every album approved for
publication ([ADR 0072](../../docs/decisions/0072-campaign-atlas-lineage-approved-pool-collections.md)
section 2). Generated rankings and review packets never authorise publication; this file does.

Not a served web artifact: it lives in the repository, is checked by `validate-public-artifacts`
(group `approved_pool`) and is consumed by `build-public-album-catalog --approved-pool`.

## Shape

```json
{ "schema_version": 1, "note": "...", "albums": [ { "master_id": 302, "round": 0, "selection_source": "editorial" } ] }
```

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int, `1` | |
| `note` | non-empty string | Short human note. |
| `albums[].master_id` | positive int | Discogs master id. Unique; `albums` sorted ascending by it. |
| `albums[].round` | int >= 0 | The expansion round that added the album (0 = original backbone). |
| `albums[].selection_source` | enum | ADR 0069's **public** vocabulary only: `editorial`, `already_published`, `graph_rich`, `coverage_gap`, `generic_candidate`. A personal-collection pick is `editorial`, never `personal_editorial`. |

**Nothing else.** The validator rejects any additional key: no scores, no rejected or deferred
candidates, no reviewer identity, no lane or bucket detail finer than the public enum, nothing that
could indicate where a candidate came from.

## Checks

- Shape (above) — `networked_players_contracts.approved_pool.approved_pool_failures`.
- Two-way: the catalog's `master_id` set must equal the pool's, and where the catalog carries
  `expansion_round` / `selection_source` (schema v2) they must agree per album —
  `approved_pool_catalog_failures`.
- Builder: with `--approved-pool`, `build-public-album-catalog` fails if it would publish an album
  outside the pool, omit a pool album (naming the recorded reason, e.g. an eligibility drop), or
  label an album differently from the pool. `--candidates` auto-fill is disabled and the
  `--editorial-albums` default fallback does not apply (pass it explicitly to keep the `editorial`
  label of the `top-albums-v1.json` albums). Lane order and labels are otherwise unchanged.

## Seeding

The initial pool was seeded from the published catalog (the pool follows the catalog once, never
afterwards): `uv run python scripts/seed_approved_pool.py --write`. `--check` re-derives the seed
and diffs it. After the seed, rounds append owner-approved entries; the file is not regenerated.

## Limits of the builder check

- Round and `selection_source` agreement is only checked for albums that carry those fields,
  which the builder emits only for a schema-v2 catalog (`--featured-albums` supplied). A
  v1-shaped build with `--approved-pool` checks the master set alone. The committed catalog is
  v2, and `validate-public-artifacts` checks rounds and labels against it on every run.
- The `--approved-pool` file must be a well-formed pool. A file that is not (including one
  containing `null`) fails the build; it is never treated as "no pool supplied".
- Keys in `data/albums/expansion-policy-v1.json` that no program reads are labelled there as
  human-review guidance. They are neither enforced nor removed.
