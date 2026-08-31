# Background-only-profiles contract (background-only-profiles-v1)

The public background-only-profiles artifact
(`apps/web/public/data/contributors/background-only-profiles.v1.json`),
produced by `networked-players-catalog build-background-only-profiles` and
validated by `validate-background-only-profiles` /
`networked_players_contracts.background_only_profiles::background_only_profiles_failures`
(ADR 0048/0060 addendum).

> **A companion artifact to `contributor-index-v1`, deliberately not a
> field on it.** Same reasoning `album-hop-distances-v1.md` already
> documents: `contributor-index-v1`'s contract is validated as an exact
> top-level key set on every `contributors[]` entry, so a new required key
> there would be a real breaking change hiding behind an unchanged
> `schema_version`.
>
> **Also closes a real gap `contributor-index-v1`'s own published data
> couldn't.** That index's `role_text_examples` field is capped to the
> five most frequent role strings per contributor. Inferring
> "background-only" from that capped sample alone (an earlier
> implementation, `apps/web/src/game/roleTaxonomy.ts`'s
> `isBackgroundOnlyRoleProfile`, did exactly this) can miss a rarer,
> lower-frequency substantive credit truncated beyond the cap -- a real
> review finding. This artifact is instead built server-side from each
> contributor's full, uncapped role-text vocabulary
> (`packages/graph-core/src/networked_players_graph_core/
> contributor_index.py`'s `_compute_role_text_counters`), so the answer is
> authoritative rather than inferred from a display sample.

## Top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1`. |
| `catalog_version` | string | The canonical `catalog/albums.v1.json` version this artifact belongs to. |
| `background_only_profiles_version` | string | `background-only-profiles-v1-<snapshot>-<hash>` -- a content hash of the sorted `artist_ids` array (order-INSENSITIVE). |
| `generated_at` | string | Explicit operator-supplied ISO datetime (never the wall clock). |
| `source` | string | Provenance note naming the source artifacts. |
| `license` | string | See `docs/DATA_AND_RIGHTS.md`. |
| `artist_ids` | array of int | Every `artist_id` (a real `contributor-index-v1` contributor) whose ENTIRE observed role vocabulary is background-engineering (Mastered By/Recorded By/Mixed By) or non-substantive (packaging/business, unknown). May be empty. Sorted ascending, no duplicates. |

## Semantics

An `artist_id` appears in `artist_ids` when
`is_background_only_role_profile` (`role_taxonomy.py`) returns `True` for
that contributor's full `role_texts` Counter: at least one credit
classifies as ENGINEERING, every ENGINEERING-classified credit is itself
background-engineering (`is_background_engineering_role`), and no credit
classifies into any category other than ENGINEERING, PACKAGING_BUSINESS,
or UNKNOWN. A contributor with no engineering credit at all is never
listed (there is nothing to background). Frontend consumers (contributor
and album detail pages) use membership in this set to visually de-emphasize
(never hide) a contributor's non-direct connections -- the same "dimmed,
not removed" language `networkExplorer.ts`'s `isDimmed()` already uses.

## Validation

`background_only_profiles_failures(artifact, catalog, contributor_index)`
checks: exact top-level key set, `schema_version == 1`, `catalog_version`
agreement with the canonical catalog,
`background_only_profiles_version` recomputation, every `artist_ids` entry
being an integer that is a real contributor in `contributor_index`, no
duplicate `artist_id`, and the array sorted ascending. A malformed entry
(e.g. a list or object from corrupt JSON) is reported as a contract
failure, never allowed to crash validation via an unguarded set operation.

## Revisit trigger

If a future surface needs a different or finer-grained background/
substantive distinction, extend `is_background_only_role_profile` and
re-version this artifact (or add a clearly-named `v2` artifact with its
own version namespace) -- never silently widen
`background-only-profiles-v1`, and never fold this data back onto
`contributor-index-v1` itself.
