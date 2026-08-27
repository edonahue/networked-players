# Public editorial seed contract (schema v1)

This contract describes `data/albums/editorial-seed-v1.json` — a **committed, public**
artifact produced by `networked-players-catalog resolve-editorial-albums`, defined in
`packages/graph-core/src/networked_players_graph_core/editorial_seed.py`
(`resolve_editorial_albums`, `editorial_seed_release_ids`).

> **Source of truth.** `editorial_seed.py` is authoritative. If this document and the
> code disagree, the code wins and this file should be updated.

## What this is, and why it is separate from the private seed

`data/private/discogs-seed.json` ([contract](discogs-seed-v1.md)) is an **ownership**
signal: release IDs derived from the operator's own Discogs collection export, never
committed, never published. `expand_one_hop`'s frontier has always come entirely from
it.

This file is an **editorial intent** signal: a human-curated list of albums the
operator wants considered for public catalog expansion, resolved to real Discogs
identities. It is **committed and public**. It reveals which albums are editorial
candidates. It reveals **nothing about the private collection** — an album can appear
here whether or not the operator owns it, and the reverse is equally true.

These are four distinct concepts and this contract keeps them distinct:

| Concept | Artifact | Committed? |
|---|---|---|
| Private collection seed | `data/private/discogs-seed.json` | no |
| **Public editorial intent** | **`data/albums/editorial-seed-v1.json`** | **yes** |
| Generated candidate selection | `local/research/catalog-expansion/*.json` | no |
| Published final catalog | `apps/web/public/data/catalog/albums.v1.json` | yes |

## Location

`data/albums/editorial-seed-v1.json`, tracked in git.

## Schema — one JSON object

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Currently 1. |
| `kind` | string | Always `"public-editorial-seed"` — a distinct literal from any private-seed or catalog `kind`/`version` string, so a build script cannot confuse the two by accident. |
| `snapshot_date` | string (`YYYYMMDD`) | The full parsed snapshot every album was resolved against. |
| `generated_by` | string | The CLI invocation that produced this file, `networked-players-catalog resolve-editorial-albums <version>`. |
| `generated_at` | string (UTC ISO 8601) | When resolution ran. |
| `note` | string | Free-text editorial context. Must never name a private collection or imply ownership. |
| `albums` | array of objects | See below. |

Each `albums[]` entry:

| Field | Type | Null? | Meaning |
|---|---|---|---|
| `query_artist` | string | yes | The original query's artist text, kept for traceability. |
| `query_title` | string | yes | The original query's title text. |
| `master_id` | int | yes | Resolved Discogs master ID. |
| `main_release_id` | int | no | The master's canonical main release — what one-hop expansion seeds on. |
| `artist_id` | int | no | Resolved Discogs artist ID (PAN, not ANV display text). |
| `artist` | string | no | Resolved display name from the matched credit. |
| `title` | string | no | Resolved title (the master's title when masters are attached, else the release's). |
| `year` | int | yes | Resolved year. |

## Rules

- **Only publishable fields.** No candidate score, no private-corpus-derived
  contributor count, no bucket label, no reviewer note. Those live in
  `local/research/catalog-expansion/` and stay there.
- **Deduplicated by `master_id`.** Two queries resolving to the same master is an
  error at resolution time (`resolve_editorial_albums` reports the second as
  `unresolved`), not something this file's schema needs to defend against.
- **Never a substitute for eligibility.** This file records identity, not a
  publication decision. `build-public-album-catalog` applies the real
  release-format policy, master genre/style gate, and curated exclusions at build
  time regardless of which seed contributed a release ID. An album resolved here can
  still fail to publish.
- **Resolution runs against the FULL parsed snapshot**, not the one-hop working set —
  that is the entire reason this file exists: to name albums the private-seed-derived
  one-hop corpus cannot reach on its own.

## How this feeds one-hop expansion

`expand_one_hop` gains an optional `--additional-seed <path>` accepting this file.
`editorial_seed_release_ids()` extracts the deduplicated, sorted `main_release_id`
list and unions it into the frontier query's seed release set, alongside (never
instead of) the private seed. The output one-hop manifest's `expansion` block records
both contributions **separately** — the private seed's existing aggregate-only
provenance (count + sha256, never IDs), plus this file's own path and content hash
(safe to record in full: this file is already public) — so a reader can always tell
which seed contributed which portion of the frontier, without either provenance being
able to imply something about the other.

## Privacy invariant

The published catalog must be byte-identical whether an album's `main_release_id`
arrived via the private seed or via this file. Nothing about which seed contributed a
release ID may reach `apps/web/public/data/**` — this file's own existence is the only
public signal, and it names editorial candidates, not private collection membership.
