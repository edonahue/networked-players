# Album-credit-membership contract (album-credit-membership-v1)

The public album-credit-membership artifact
(`apps/web/public/data/albums/credit-membership.v1.json`), produced by
`networked-players-catalog build-album-credit-membership` and validated by
`validate-album-credit-membership` /
`networked_players_contracts.album_credit_membership::album_credit_membership_failures`
(ADR 0058).

> **The single canonical answer to "who's credited on album X."** Before
> this artifact, that question was answered three different, disagreeing
> ways across `challenge.v2.json`, Connection Guesser/Record Routes, and
> the pathfinding graph. This artifact settles it for the 140-album
> catalog: for each album, the definitive credited-contributor list on
> that album's own `main_release_id` — the same release
> `assemble_album_catalog` already chose, never re-derived here. It does
> not replace the traversal denylist (`graph.py`) or the game-round
> performer allowlist (`eligibility.py`) — both keep governing what they
> already govern; this artifact only answers album membership.

## Top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1`. |
| `catalog_version` | string | The canonical `catalog/albums.v1.json` version this artifact belongs to. Validation requires exact agreement. |
| `album_credit_membership_version` | string | `album-credit-membership-v1-<snapshot>-<hash>` — a content hash over every album's `main_release_id` and full, order-sensitive `credits[]` list (a fingerprinted content pool, like `pathfinding_graph_version`, not an order-insensitive lookup index). |
| `generated_at` | string | Explicit operator-supplied ISO datetime (never the wall clock). |
| `source` | string | Provenance note. |
| `license` | string | See `docs/DATA_AND_RIGHTS.md`. |
| `albums` | array | See below. Exactly one entry per catalog album — never a subset. |

## `albums[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `album_id` | string | Canonical catalog album id (must exist in `catalog/albums.v1.json`). Unique across the array. |
| `main_release_id` | int | Must equal the catalog's own `main_release_id` for this album exactly — this artifact never invents or re-derives a release choice. |
| `credits` | array of object | Every playable, linked, non-placeholder credit row on this release (`CreditGraph.credit_rows_for_releases`'s own filter — the same one `connection_rounds.py`/`role_mode_candidates.py` already use for equivalent queries). May be empty for a release with thin credits — never dropped, always present as an honest empty list. |

## `credits[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `artist_id` | int | The Discogs PAN artist id. |
| `name` | string | Canonical PAN name — never an ANV. |
| `anv` | string \| null | As-credited display text, when it differs from `name`. |
| `role_text` | string \| null | Verbatim original role text. |
| `credit_scope` | string | One of `release_artist`, `release_credit`, `track_artist`, `track_credit`. |
| `track_position` | string \| null | Present for track-scoped credits. |
| `track_title` | string \| null | Present for track-scoped credits. |

No `is_linked` field: every row in this artifact is, by construction,
already linked (`credit_rows_for_releases` filters to `artist_id IS NOT
NULL`) — carrying a field that would always be `true` would be redundant
rather than informative. Unlinked/evidence-only names are not represented
here; they remain visible where other artifacts (e.g. `challenge.v2.json`)
already carry them alongside real hop evidence.

## Validation

`album_credit_membership_failures(membership, catalog)` checks: exact
top-level key set, `schema_version == 1`, `catalog_version` agreement,
`album_credit_membership_version` recomputation, exactly one entry per
catalog album (no missing, no extra, no duplicate `album_id`), each
album's `main_release_id` agreeing exactly with the catalog's own choice,
every `credit_scope` in the valid enum, and a scan for forbidden
substrings/inference-implying phrases (the same list `catalog.py` already
enforces).

## Revisit trigger

If a future consumer needs personnel from more than one release per album
(e.g. combining a reissue's bonus-track credits with the main release),
that is a real, separate design decision — extend this artifact
explicitly with a new field, or add a clearly-named `v2`, never silently
widen `main_release_id` into a list without updating every consumer that
currently assumes exactly one.
