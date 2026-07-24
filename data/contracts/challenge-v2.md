# Challenge artifact contract (schema v2)

This contract describes the album-centered static challenge artifact produced by
`networked-players-catalog build-challenge-from-dump`, defined in
`packages/graph-core/src/networked_players_graph_core/challenge.py`
(`CHALLENGE_SCHEMA_VERSION`, `build_challenge_v2`, `validate_challenge`). The actual
structural checks live in the dependency-free
`networked_players_contracts.challenge::challenge_failures` (no lxml/pyarrow/duckdb) --
`validate_challenge` delegates to it so the two can never drift, same pattern as Record
Routes (`data/contracts/record-routes-v1.md`, ADR 0046). `validate-public-artifacts`
(`make check`) also runs it against the real committed
`apps/web/public/data/challenge.v2.json` on every change.

> **Source of truth.** `challenge_failures` (contracts) is authoritative. If this
> document and the code disagree, the code wins and this file should be updated.

v2 evolves the de-facto v1 artifact (`apps/web/src/data/challenge.ts`,
`public/data/challenge.v1.json`, ADR 0012) from artist-path-centered to
**album-centered**: albums are the top-level entry points into the credit network;
releases are demoted to evidence beneath the hops that connect two albums' artists.
See `data/albums/README.md` for how the album list itself is selected.

## Top-level shape

A challenge v2 artifact is a single JSON object with exactly these keys:
`schema_version`, `provenance`, `albums`, `artists`, `paths`, `releases`. No other
top-level key is permitted; `validate_challenge` rejects unknown or missing keys.

## `schema_version`

Integer, always `2` for this contract.

## `provenance`

| Field | Meaning |
| --- | --- |
| `source` | Human-readable source description (e.g. "Discogs monthly data dump (CC0), one-hop working set"). |
| `license` | Rights/reuse note; points at `docs/DATA_AND_RIGHTS.md`. |
| `snapshot_date` | The source dump snapshot the underlying one-hop dataset was expanded from (`YYYYMMDD`). |
| `generated_by` | Tool + version string that produced the artifact. |
| `graph_core_version` | `networked_players_graph_core.__version__` at generation time. |
| `catalog_version` | The canonical `apps/web/public/data/catalog/albums.v1.json` this artifact's album set was resolved from (`--albums` pointed at that file), or `null` for a hand-written `{artist,title}` query list not built from it. See ADR 0043 — that catalog is the single source of truth for which albums exist across every real public surface; this artifact never re-derives its own album set independently. When a caller passes the canonical catalog into `challenge_failures`/`validate_challenge` and this field is non-`null`, it must equal the catalog's own `catalog_version` exactly -- `null` is never itself a failure (it's the documented hand-written-list case above). |
| `note` | Honest caveats: the private collection seed is never published; the album list is editorial, not a ranking. |

No part of the artifact may contain seed identifiers, seed counts, seed hashes, or any
private path. `validate_challenge` rejects a literal `seed` key found anywhere in the
artifact's object tree — not just inside `provenance` — and separately scans the
serialized artifact for `local/`, `data/private`, `/home/`, `DISCOGS_TOKEN`, and `.ssh`.
The `note` field's prose may still say the word "seed" (e.g. "the private collection seed
is never published") — the check inspects dict *keys*, not free text, so that sentence is
fine.

## `albums`

One row per matched editorial album query (see `data/albums/top-albums-v1.json`).

| Field | Type | Null? | Meaning |
| --- | --- | --- | --- |
| `id` | string | no | `"master-<master_id>"` if the release has a master, else `"release-<main_release_id>"`. |
| `master_id` | int | yes | Discogs master ID, when the matched release has one. |
| `main_release_id` | int | no | The release ID this album's evidence resolves to (positive). |
| `title` | string | no | Master title if a masters dataset was attached and matched; otherwise the release title. |
| `artist_id` | int | no | The playable (linked) artist ID for this album's release-artist credit. |
| `artist` | string | no | Canonical artist name (never an ANV). |
| `year` | int | yes | 4-digit year parsed from the release's `released` field, or the master's `year` when attached. |
| `cover_image` | object or null | yes | `{uri, uri150, width, height}` when enriched via the Discogs API (optional, rate-limited, main-release-only per ADR 0012); `null` otherwise. Presentational only — never load-bearing evidence (`docs/DATA_AND_RIGHTS.md`). |

## `artists`

Every artist ID referenced as a path endpoint or intermediate bridge.

| Field | Type |
| --- | --- |
| `artist_id` | int |
| `name` | string (canonical name, never an ANV) |

## `paths`

One row per curated evidence path between two albums' artists.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | `"path-NN"`. |
| `label` | string | `"{from album title} → {to album title}"`. |
| `description` | string | Hop-count summary; never a claim of influence (see "Influence versus participation" in `docs/DATA_AND_RIGHTS.md`). |
| `from_album_id` / `to_album_id` | string | References into `albums[].id`. |
| `from_artist_id` / `to_artist_id` | int | References into `artists[].artist_id`. |
| `hops` | array | `{release_id, artist_a_id, artist_b_id}`; `release_id` must reference a row in `releases`. |

## `releases`

Evidence, not top-level content: every release referenced by at least one hop, with
release metadata (same fields as `discogs-release-v2.md`'s `releases` table, minus
`images` — cover art lives only on `albums[].cover_image`) plus a `credits` array
**filtered to only the linked artists that are hop endpoints on that release** — not
the release's full credit list. This mirrors v1's evidence-first framing but keeps the
artifact small: a release with 40 real credits contributes only the 2 rows that prove
the connection.

## Evidence and identity rules (unchanged from the release/master contracts)

- PAN (`artist_id`) and ANV (display name) stay separate; `artists[].name` and
  `albums[].artist` are always canonical names, never a per-credit ANV.
- A non-linked contributor (`is_linked=false`) never becomes a node in `artists` or a
  path endpoint; it can only appear inside a `releases[].credits` row as evidence, and
  only when it happens to also be a matched hop endpoint (which by construction it
  never is, since hop endpoints are always linked).
- Discogs artist ID 194 ("Various") is excluded from the graph entirely — it is a
  compilation placeholder, not an individual.
- A credit is evidence of documented participation, never a claim of influence,
  friendship, or creative lineage.

## Deliberately not included (v2)

A materialized full-graph export (see `data/contracts/graph-snapshot-v1.md` — a
separate, non-published dataset). Track-level evidence (v2 paths connect via
release-artist credits only, matching how albums are matched). Add via a
schema-version bump when a real need appears.

## Validation

`networked-players-catalog validate-challenge --input <path>`: structural checks
(exact top-level keys, `schema_version == 2`, required provenance fields, every hop's
`release_id`/artist IDs resolve into `releases`/`artists`, every album's
`main_release_id` positive, the `catalog_version` cross-check above when a catalog is
given) plus the leak scan described above. `build-challenge-from-dump`
always calls this before writing.

`networked-players-catalog validate-public-artifacts` (`make check`) re-runs the same
dependency-free checklist against the real committed `challenge.v2.json`, cross-checked
against the real committed catalog -- the CI gate that catches a defect in an
already-published artifact that no other check exercises.
