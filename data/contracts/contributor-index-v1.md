# Contributor index contract (contributor-index-v1)

The public contributor index
(`apps/web/public/data/contributors/index.v1.json`), produced by
`networked-players-catalog build-contributor-index` and validated by
`validate-contributor-index` /
`networked_players_contracts.contributor_index::contributor_index_failures`
(ADR 0048).

> **Deliberately derived from already-published artifacts only.** This index
> is built entirely from `apps/web/public/data/challenge.v2.json`,
> `apps/web/public/data/routes/{universe,rounds}.v1.json`, and (ADR 0058
> Slice 8) `apps/web/public/data/evidence/release-registry.v1.json` — never a
> fresh full-corpus DuckDB query. The evidence registry is itself an
> already-published artifact, so consuming it here doesn't add a dependency
> on the private one-hop corpus; it only supplies `decade_activity`'s
> per-release years. A contributor's `connection_count`/
> `neighboring_contributor_ids` reflect their degree **within the
> challenge/routes artifacts only**, never the private full corpus.

## Top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1`. |
| `catalog_version` | string | The canonical `catalog/albums.v1.json` version this index belongs to. Validation requires exact agreement with the catalog, and with both source artifacts' own `provenance.catalog_version` at build time. |
| `contributor_index_version` | string | `contributor-index-v1-<snapshot>-<hash>` — a content hash of each contributor's `artist_id`/`name`/`role_categories`/`albums`/`evidence`, sorted by `artist_id` (order-INSENSITIVE: this is a lookup index, like `album-art-v1`, not a fingerprinted content pool). |
| `generated_at` | string | Explicit operator-supplied ISO datetime (never the wall clock). |
| `source` | string | Provenance note naming the source artifacts. |
| `license` | string | See `docs/DATA_AND_RIGHTS.md`. |
| `contributors` | array | See below. May be empty. |

## `contributors[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `artist_id` | int | The Discogs PAN artist id. Unique across the array. |
| `name` | string | Canonical PAN name — never an ANV (ADR 0043 Finding 1's lesson). |
| `role_categories` | array of string | Distinct `role_taxonomy.RoleCategory` values observed across this contributor's credited role text, sorted and deduped. Never empty; `["unknown"]` when nothing classifies. |
| `role_text_examples` | array of string | Up to 5 distinct verbatim role-text strings actually observed, ranked by frequency — evidence, not a summary. |
| `albums` | array of string | Canonical catalog album ids (must exist in the catalog) whose documented path or route this contributor's credits help establish — **not** a claim that this is "their" album; frontend copy must say "co-credited on a documented release connecting these albums," never "worked on"/"appears on this album." Sorted, non-empty. |
| `decade_activity` | array of int | Decades (e.g. `1990`) derived from the real release year of this contributor's own evidence releases (via the evidence-release registry, keyed by `evidence[].release_id`), sorted — not the `year` of a connected catalog album, which may differ from the evidence release's own year. |
| `connection_count` | int | This contributor's degree within the published `challenge.v2.json` + `routes/rounds.v1.json` graph only. |
| `neighboring_contributor_ids` | array of int | Other contributors directly adjacent via a shared hop, ranked by shared-hop count then id, capped at 20. Every id must itself be a contributor in this same index. |
| `evidence` | array of object | Up to 10 `{release_id, role_text}` pairs, sorted, resolving against a release referenced by either source artifact. |
| `interesting_next_step` | object or `null` | ADR 0060 (amended 2026-08-31). `{artist_id, reason}` naming one of this contributor's own `neighboring_contributor_ids` whose `role_categories` are ENTIRELY DISJOINT from this contributor's own — a real structural fact (a genuinely different kind of credited collaborator), never an inferred claim about interest or importance — AND excluding any candidate whose ENTIRE shared connection to this contributor is background-engineering-only (every hop between them is Mastered By/Recorded By/Mixed By on at least one side; a pair that ALSO shares even one substantive-role hop is never excluded on this basis). Ties among the remaining candidates break toward the LOWEST `connection_count` (deliberately anti-hub — never the highest), then `artist_id`. `null` when no neighbor qualifies — this can now mean either that no role-disjoint neighbor exists at all, or that one exists but every connection to them is background-engineering-only; both are the same honest "nothing to suggest here," never a fabricated pick. |

## Validation

`contributor_index_failures(index, catalog)` checks: exact top-level key set,
`schema_version == 1`, `catalog_version` agreement with the canonical catalog,
`contributor_index_version` recomputation, every `albums[]` entry resolving
against the catalog, every `role_categories` value being a real
`RoleCategory`, every `neighboring_contributor_ids` entry resolving to another
contributor in the same index, `interesting_next_step` being either `null` or
a real neighbor of this same contributor with a non-empty `reason`, no
duplicate `artist_id`, and a scan for forbidden substrings/inference-implying
phrases ("worked with", "collaborated with", "influenced" — the same list
`catalog.py` already enforces).

## Revisit trigger

If a future exploration-graph tier (Slice D) or Connect Two Records (Slice F)
needs contributor data beyond what `challenge.v2.json`/`routes/*.json` cover,
extend the two source artifacts first, or add a clearly-named `v2` index with
its own version namespace — never silently widen `contributor-index-v1` to
depend on the private one-hop corpus. This is the same discipline that
produced `data/contracts/album-hop-distances-v1.md` (ADR 0048 addendum): a
new field's data belongs in a new companion artifact, never grafted onto
this exact-key-set contract in place.
