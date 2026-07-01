# From source data to this project's normalized schema

How raw Discogs fields (dump XML per `raw-dump-schema.md`, API JSON per
`api-schema.md`) become this project's own normalized rows. The authoritative
schema definitions are `packages/catalog/src/networked_players_catalog/discogs/parquet.py`
(code, wins on any disagreement) and `data/contracts/discogs-release-v2.md`
(human/agent-readable tracking doc) — this page explains the *mapping decisions*
between source and output, not the output schema itself (don't duplicate that
table here; read it there).

## Two parsers, one output shape

`releases.py` (dump XML, `parse-releases` CLI) and `demo_challenge.py` (API JSON,
`build-demo-challenge` CLI) are separate parsers reading different source formats,
but they're deliberately kept structurally aligned — same `credit_scope` vocabulary,
same PAN/ANV separation, same track-scope-only-from-real-nesting rule. Wherever this
page says "the parser," it means "both parsers, identically," unless noted
otherwise.

## Identity: PAN, ANV, and the source data's third concept (aliases)

- **PAN** (`artist_id` in the output) comes directly from the source's `id` — the
  dump XML's `<artist><id>` child or the API JSON's `artist.id`. This is the stable
  identity key.
- **ANV** (`anv` in the output) comes directly from the source's `anv` — a
  *per-credit* display override, kept as a separate field, never merged into `name`.
- **`is_linked`/`playable_identity`** are derived, not sourced directly: `true` only
  when the source `id` is present and a positive integer (a real Discogs artist ID),
  `false` for an unlinked/free-text-only credit (`<artist>` with no `<id>`, or an API
  credit object with no `id` field). An unlinked credit is retained as evidence
  (`name` is kept) but never becomes a graph node.
- **Aliases are not modeled at all yet.** `raw-dump-schema.md` documents
  `artists.xml.gz`'s `aliases` field — a real, *separate* identity-linking concept
  (different artist IDs Discogs' own editors consider the same or related person).
  Nothing in this project's current schema represents this; it would require an
  artist-dump parser, which doesn't exist yet (deferred per `AGENTS.md`).

## `credit_scope`: derived from structure, never inferred from text

The output's four `credit_scope` values (`release_artist`, `release_credit`,
`track_artist`, `track_credit`) map directly to which source container a credit
came from:

| `credit_scope` | Dump XML source | API JSON source |
| --- | --- | --- |
| `release_artist` | `<release><artists><artist>` | `artists[]` |
| `release_credit` | `<release><extraartists><artist>` | `extraartists[]` |
| `track_artist` | `<release><tracklist><track><artists><artist>` | `tracklist[].artists[]` |
| `track_credit` | `<release><tracklist><track><extraartists><artist>` | `tracklist[].extraartists[]` |

The critical rule, shared by both parsers: a credit is only ever `track_artist`/
`track_credit` when the source **genuinely nests** an artist under a specific track
element. A release-level extra-artist credit with a non-empty `tracks` free-text
field (e.g. `"A2"`, meaning "this credit applies to track A2") but *no* actual
nested track-level entry stays `release_credit` scope — the free text is preserved
verbatim as `credited_tracks_text`, but never parsed to synthesize a `track_artist`
row. Evidence is kept; a claim beyond what the structure actually shows is not
manufactured. This rule is documented once here because it's easy to reach for
"just parse the tracks string" as a shortcut — it isn't a shortcut this project
takes.

## Fields the output schema deliberately omits (see `raw-dump-schema.md` for the full source list)

`data/contracts/discogs-release-v2.md`'s `releases` table has no
`labels`/`formats`/`genres`/`styles`/`notes`/`identifiers`/`videos`/`companies`
fields, even though all of them are real, present fields in the dump XML
(`raw-dump-schema.md` documents each with a real example). This is intentional
scope, not an oversight: schema v2 is the smallest slice needed to prove
release/track/credit evidence with PAN/ANV correctness. Extending it is real,
future work (`docs/BUILD_PLAN.md` Milestone 11: "Version normalized artist,
master, and label schemas as those parsers are added") — this page exists so that
work starts from an accurate list of what's actually available, not a guess.

## Source-of-truth reminders (don't duplicate these elsewhere)

- Output schema field list/types: `data/contracts/discogs-release-v2.md` and
  `parquet.py`.
- Real dump/API field structure: `raw-dump-schema.md` and `api-schema.md` in this
  directory.
- Sizes, record counts, parse throughput, memory: `docs/DATA_SIZING.md`.
- Pipeline architecture and source-role decisions (dump vs. API vs. private seed):
  `docs/DISCOGS_INGESTION.md`.
