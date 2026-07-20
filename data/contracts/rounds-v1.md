# Game-rounds contract (schema v1)

This contract describes the flagship game's static artifact pair —
`universe.v1.json` and `rounds.v1.json` — produced by
`networked-players-catalog build-rounds-from-dump`. Defined in
`packages/graph-core/src/networked_players_graph_core/rounds.py`
(`build_round_hop`, `build_round_from_path`, `validate_rounds_artifact`,
`ROUNDS_SCHEMA_VERSION`).

> **Source of truth.** `rounds.py` owns generation and
> `packages/contracts/src/networked_players_contracts/rounds.py` owns the
> dependency-free validator used by the web build and constrained (Pi) workers.
> If this document and the code disagree, the code wins and this file should
> be updated.

## Why two files, not one

`universe.v1.json` is small (the bounded launch album list only) and safe to
inline/fetch eagerly. `rounds.v1.json` is the full round pool — potentially
several hundred entries with evidence — and is fetched at runtime by the game
route rather than bundled into every page, per ADR 0002's static-first
posture. See `docs/DATA_SIZING.md` for measured payload size once a real pool
has been generated.

## Relationship to `challenge-v2.md`

Both artifacts describe the same kind of album-centered evidence path, but for
different audiences and eligibility rules:

- `challenge.v2.json` (the album browser) uses the graph's existing broad
  `credit_edges` eligibility (any collaborative role, per ADR 0035) and shows
  every path the generator finds.
- `rounds.v1.json` (the flagship game) additionally requires every hop to pass
  the narrower, fail-closed instrument/vocal performer allowlist
  (`eligibility.py::is_performer_role`) — see
  [ADR — performer-role allowlist](../../docs/decisions/) once written. A path
  that is valid evidence for the album browser may still be excluded from the
  game if its only connecting credit is non-performer (e.g. a shared producer).

## `universe.v1.json` — top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always 1. |
| `pool_version` | string | Identifies one frozen generation of the round pool, e.g. `rounds-v1-20260719`. Referenced by the daily manifest (see below) so a rebuild under a new `pool_version` never silently changes an already-assigned daily date. |
| `provenance` | object | Same shape as `challenge-v2.md`'s `provenance`: `source`, `license`, `snapshot_date`, `generated_by`, `graph_core_version`, `note`. |
| `counts` | object | `{one_hop, two_hop, daily_eligible}` — the real achieved counts, not a target. |
| `albums` | array | Every album that appears as a round endpoint. Same row shape as `challenge-v2.md`'s `albums[]`: `{id, master_id, main_release_id, title, artist_id, artist, year, cover_image}`. |

## `rounds.v1.json` — top-level shape

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always 1. |
| `pool_version` | string | Must match the paired `universe.v1.json`. |
| `provenance` | object | Same shape as above. |
| `rounds` | array | See below. |
| `releases` | array | Evidence releases referenced by any round's hops. Same shape as `challenge-v2.md`'s `releases[]` (release fields plus a `credits` array filtered to the hop-endpoint artists). |
| `artists` | array | `{artist_id, name}` for every artist referenced by any round (endpoints and bridges). |

## `rounds[]` fields

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | `round-NNNNNN`, stable within one `pool_version`. |
| `kind` | `"one_hop"` \| `"two_hop"` | First-class, not inferred from `len(hops)` at render time. |
| `difficulty` | `"easy"` \| `"medium"` \| `"hard"` \| `"very_hard"` | Derived from hop count and evidence strength at generation time. |
| `from_album_id` / `to_album_id` | string | Album IDs, referencing `universe.v1.json`'s `albums[].id`. |
| `from_artist_id` / `to_artist_id` | int | The two endpoint artists. |
| `hops` | array | 1 entry for `one_hop`, 2 for `two_hop`. See below. |
| `distractors` | array | Precomputed at generation time, never client-computed (ADR 0002: no runtime graph dependency). `{album_id, reason}`, where `reason` is a presentational-only hint (e.g. `same_decade_no_path`), never shown to players as a factual claim. |

## `hops[]` fields

`{release_id, artist_a_id, artist_b_id, role_a, role_b, quality_flags}`

- `release_id`, `artist_a_id`, `artist_b_id`, `quality_flags` — identical meaning to
  `album-cohort-connectivity-v1.md`'s `hops[]`: exactly one strength flag
  (`co_billed_release_artists` / `performer_credit` / `non_performer_only`) and
  exactly one scope flag (`same_recording` / `release_scope_credit`) from the same
  `classify_hop_quality` used by cohort scoring.
- `role_a` / `role_b` — the literal Discogs `role_text` that satisfied
  `is_performer_role` for that artist on that release (e.g. `"Vocals"`,
  `"Guitar"`). This is the "preserve exact evidence rows establishing
  eligibility" requirement made concrete: unlike the cohort/album surfaces, a
  game round's hop must always have a real, displayable performer role on
  both sides — never null, never inferred from a bare release-artist billing.

## Rules

- **Every hop must independently pass the performer allowlist.** A path where
  any hop's evidence is only a non-performer credit (e.g. shared producer,
  co-billed release artist with no instrument/vocal role text) is not a valid
  round, even though the same path might be valid evidence for the album
  browser or cohort. `role_a`/`role_b` being non-null is the artifact-level
  proof of this rule.
- **`kind` must match `len(hops)`**: `one_hop` implies exactly 1 hop,
  `two_hop` implies exactly 2.
- **Every hop's `release_id`/`artist_a_id`/`artist_b_id` must resolve** against
  the artifact's own `releases[]`/`artists[]` — no dangling references.
- **Every `from_album_id`/`to_album_id`/distractor `album_id`** must resolve
  against `universe.v1.json`'s `albums[]`.
- **Never implies a relationship beyond a documented credit.** Same standing
  rule as the cohort contract: no generated text may say "worked with,"
  "collaborated with," or "influenced."
- **Never leaks private data.** Same forbidden-substring scan as every other
  public artifact (`/home/`, `data/private`, `local/`, `DISCOGS_TOKEN`, `.ssh`),
  plus the literal-`seed`-key scan `challenge.py` already uses.
- **Validation:** `validate_rounds_artifact()` (graph-core, generation-time)
  and `rounds_failures()` (dependency-free, `packages/contracts`, reusable on
  the Pi fleet and in the web build) both check the exact key sets above, hop
  quality-flag arity, `kind`/hop-count agreement, and reference resolution.
