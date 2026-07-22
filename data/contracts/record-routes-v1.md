# Record Routes contract (record-routes-v1)

The real path-guessing mode's artifact pair
(`apps/web/public/data/routes/universe.v1.json` /
`apps/web/public/data/routes/rounds.v1.json`), produced by
`networked-players-catalog build-record-routes` and validated by
`validate-record-routes` /
`networked_players_contracts.record_routes::record_routes_failures`
(ADR 0046).

> **Not the Connection Guesser's contract.** Record Routes answers a
> **different question**: given two real albums, how many documented-credit
> hops connect them (album → artist → album, one or two hops), and who is the
> connecting artist? This is the `from_album_id`/`to_album_id`/`hops[]` **path**
> semantic (`networked_players_graph_core.rounds`/`rounds_generator`'s
> discovery, reused here), not the Connection Guesser's "performer credited on
> both displayed albums" **intersection** semantic
> (`data/contracts/game-rounds-v1.md`). Record Routes **never** reads or
> writes `apps/web/public/data/game/rounds.v1.json`, `game/universe.v1.json`,
> or the Connection Guesser's daily manifest — separate artifact namespace,
> separate `mode`, separate validator, separate Pi job.

## Top-level shape

Both `universe.v1.json` and `rounds.v1.json` carry:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1`. |
| `mode` | string | Always `"record_routes"` — unambiguous identity, never confusable with the Connection Guesser or its daily manifest. |
| `pool_version` | string | Membership hash: `routes-v1-<snapshot>-<hash of sorted route ids>`. Unchanged by an edit to a route's evidence/distractors when the set of routes is unchanged. |
| `provenance` | object | Must match exactly between `universe` and `rounds`. Includes `catalog_version` (the canonical `catalog/albums.v1.json` this pool's albums came from) and `artifact_version` (see below). |

`universe.v1.json` additionally carries `counts` (`one_hop`/`two_hop`/
`daily_eligible`) and `albums[]` (art-free — see below). `rounds.v1.json`
additionally carries `rounds[]`, `releases[]`, `artists[]`.

## `artifact_version`

`provenance.artifact_version` = `routes-artifact-v1-<snapshot>-<content hash of
the published rounds array IN ITS PUBLISHED ORDER>` — the complete-content
version, order-sensitive, mirroring the Connection Guesser's `artifact_version`
(ADR 0043/0045's addenda). Changes on any published field changing or a
reordering, even with identical `pool_version` membership.

## `rounds[]` entry shape

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | `route-<10 hex chars>` — a **content-derived stable id** (`stable_route_id`): a hash of the sorted endpoint album ids plus the ordered hop signatures (release id + the unordered artist pair per hop). Deliberately **not** the ordinal `round-000001` id `generate_round_pool` assigns internally — ADR 0046 requires the published id survive regeneration/reordering. |
| `kind` | `"one_hop"` \| `"two_hop"` | Path length. |
| `difficulty` | string | As scored by the shared path-discovery logic. |
| `from_album_id` / `to_album_id` | string | The two endpoint albums (must differ). |
| `from_artist_id` / `to_artist_id` | int | The endpoint albums' representative artists. |
| `hops[]` | array | 1 entry for `one_hop`, 2 for `two_hop`: `{release_id, artist_a_id, artist_b_id, role_a, role_b, quality_flags}`. |
| `distractors[]` | array | `{album_id, reason}` — decoy albums, never one of the round's own endpoints. |

## Albums are art-free

`universe.albums[]` never carries `cover_image` or `art` — cover art is
resolved by canonical album id from the shared album-art registry
(`data/contracts/album-art-v1.md`, ADR 0045), exactly like the Connection
Guesser. This keeps `artifact_version` permanently insensitive to cover-art
changes.

## Validation

`record_routes_failures(universe, rounds)` (pure, Pi-safe) checks: exact
top-level key sets; `schema_version`/`mode` literals on both artifacts;
`pool_version` agreement; exact `provenance` match; required provenance
fields; art-free albums; per-round id format + recomputation; per-round key
set, difficulty/kind validity, hop count matching `kind`, hop shape (reusing
the same strength/scope quality-flag checks as the legacy path contract);
endpoints differ and both exist in the universe; distractors exist in the
universe and are never an endpoint; `pool_version`/`artifact_version`
recomputation; a real-Discogs-source check; a recursive `seed`-key scan; and
forbidden-substring/influence-phrase scans.

## Relationship to the legacy `rounds.py` contract

`networked_players_graph_core.rounds`/`rounds_generator` (PR #43-era,
`build-rounds-from-dump`) already implemented this path semantic but with
ordinal ids, an operator-supplied `pool_version`, no `mode`, and embedded
`cover_image`. `record_routes.py` **reuses** its tested discovery
(`generate_round_pool`) and universe assembly (`build_rounds_v1`), then
replaces the ids and adds the missing identity/versioning/art-free guarantees.
`build-rounds-from-dump` remains available but is explicitly legacy/
exploratory — `build-record-routes` is the correct production path.
