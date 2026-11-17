# Collection contract (schema v1)

A Collection is a reviewed, thematic **view over the published catalog**: its records are
catalog albums, and its bridge players, journey and playable pairs are facts of the
performer-only pathfinding graph (`graph.v4.json`, ADR 0068). Decision record:
[ADR 0074](../../docs/decisions/0074-collections-contracts.md). Validator:
`packages/contracts/src/networked_players_contracts/collection.py`
(`collection_failures`, `collections_failures`); builder:
`networked-players-catalog promote-collection` (`collection_promote.py`). If this note and the
code disagree, the code wins.

> **Nothing is published by this contract.** No real collection exists in the repository.
> Publishing one is owner-reviewed work (`docs/REVIEW_PACKET.md`, "Publishing a Collection").
> Public copy says "Collection"; it never suggests the owner's private record collection.

## Paths

- `apps/web/public/data/collections/index.v1.json` — the index.
- `apps/web/public/data/collections/<collection_id>.v1.json` — one file per collection.

New directory, deliberately separate from `cohorts/` (the v1 artist-to-artist pipeline with
`release-...` ids). A page loads the index (tiny) and then one collection file, so a collection's
payload is never paid for by a visitor who does not open it. With no `collections/` directory,
`validate-public-artifacts` passes (nothing published). A collection file the index does not list
fails validation.

### Index

```json
{
  "schema_version": 1,
  "collections": [
    {
      "collection_id": "slug",
      "title": "Public title",
      "artifact_path": "/data/collections/slug.v1.json",
      "record_count": 8,
      "collection_version": "collection-v1-0123456789ab"
    }
  ]
}
```

Entries are unique and sorted by `collection_id`; each field must agree with the file.

## Collection file

| Field | Type | Rule |
| --- | --- | --- |
| `schema_version` | int | `1`. |
| `collection_id` | string | Lowercase slug (`a-z`, `0-9`, hyphens), 1..64 chars. |
| `title` | string | Non-empty, at most 120 chars. Owner-written; the only way a working title becomes public is by the owner passing it as the title. |
| `intro` | string | Non-empty (required for publication), at most 1500 chars. Owner-written, never generated. |
| `generated_at` | string | An ISO-8601 timestamp with offset or `Z` (e.g. `2026-01-01T00:00:00Z`); a label, excluded from the content version. |
| `records` | string[] | Ordered catalog album ids (`master-...`); 4..24; distinct; **all in the catalog**; at least **3 distinct primary artists** (the E1 gate's qualifying-cluster rule; artist identity is the catalog's `artist_id`). |
| `bridge_players` | object[] | 1..12 entries `{artist_id, name, records}`. `name` equals the graph's name. `records` lists at least 2 distinct records of the collection **spanning at least 2 distinct primary artists**; the player must be **adjacent in `graph.v4` to each listed record's album anchor** (credited as a performer on it). |
| `journey` | object[], optional | Ordered hops (below). |
| `playable_cohort` | object, optional | `playable-cohort-v2` (see that contract). |
| `attribution` | `{label, source_url}`, optional | Only for a genuinely sourced theme. `source_url` is a public `https://` page: it has a host, no credentials, no query string or fragment, and no personal-page path segment (`user`, `users`, `collection`, `mycollection`, `wantlist`, `mywantlist`, `people`, `profile`, `seller`, `sell`, `list`, `lists`) on any domain. |
| `provenance` | object | `{inputs, collection_version}` (below). |

### Journey hop

`{from_record, to_record, via, via_names, evidence_release_ids}`. Hops chain
(`hops[i].to_record == hops[i+1].from_record`) and never revisit a record.

- `via`: ordered performer artist ids (positive, distinct, 1..7). `via[0]` is adjacent to
  `from_record`'s anchor and `via[-1]` to `to_record`'s anchor in `graph.v4`.
- `via_names`: one name per `via` entry, equal to the graph's.
- `evidence_release_ids`: one per consecutive `via` pair, **exactly the graph's
  `evidence_release_ids` for the directed slot `via[i] -> via[i+1]`**. A single shared performer
  (`len(via) == 1`) has no pairs and an empty list.

Every `via` node is a real performer node (anchors are negative ids and refused), so a route is
performer-only by construction of the graph.

### Bridge rule: bridges connect different artists

A catalog album's primary artist is adjacent to their own anchor, so one artist's discography would
otherwise "bridge" nothing but itself. The rule:

- A bridge player's `records` must span **at least two distinct primary `artist_id`s**.
- A collection's own primary artist **may** be a bridge player, but only on that basis: they are
  credited as a performer on at least one record by a different primary artist.
- A journey hop, and a playable pair, between two records with the **same primary artist** is
  refused (validator and builder): it connects no one.

### Route length equals the site's search limit

`len(via)` is at most **5**, i.e. at most 4 performer-to-performer hops
(`hop_count = len(via) - 1`). That is exactly what the site searches: `findAlbumRoute`
(`apps/web/src/game/pathfindingGraph.ts`, called with `maxHops = 4` by `connect.ts`) runs a BFS
with budget `4 + ALBUM_ANCHOR_HOP_BUDGET (2)`; the two anchor hops (album to first performer, last
performer to album) are stripped (`stripAlbumAnchors`), leaving performer-to-performer hops. One
shared performer is therefore 0 hops. Every published route is reachable by the site's own search.

### Provenance and version

- `provenance.inputs` declares exactly `catalog` and `pathfinding_graph`, each a content version
  string. Both must equal the current artifacts' versions (see ADR 0072 section 1 and
  `artifact-lineage-v1.md`); otherwise validation fails and the collection must be re-promoted
  and re-reviewed.
- `provenance.collection_version` = `collection-v1-` + `content_hash` (12 hex) of the collection
  with `provenance` and `generated_at` removed.

## Private-field guard and text checks

Exactly what the code does (`collection.py`):

1. **Keys.** Validation fails if any key at any depth is `notes`, `note`, `review_note`,
   `reviewer`, `reviewed_by`, `rejected`, `working_title`, `kept_records`, `input_hash`, `private`,
   or ends in `_private`.
2. **Every string value** (names, titles, ids, URLs, all of it) is checked for path and credential
   text: `/home/` (not preceded by a word character), `data/private`, lowercase `local/` followed by
   a word character, `DISCOGS_TOKEN`, `.ssh`. These are anchored so ordinary music text ("Local
   Natives", "Far From My Home") is not caught.
3. **`title`, `intro` and `attribution.label`** (owner-written copy) are checked, with word
   boundaries, for phrases that suggest the owner's own collection: `my collection`, `my records`,
   `my record collection`, `my shelf`, `my library`, `personal collection`, `private collection`.
   "my recordings" and "Far From My Home" pass.
4. **`title` and `intro` only** are additionally checked for inferred influence or a working
   relationship: `worked with`, `collaborated with`, `influenced`. Names and record titles are
   facts, not claims, and are not checked for these.
5. `attribution.source_url` and `generated_at` are checked as described in their rows above.
6. **Directory.** Every entry of `collections/` must be `index.v1.json` or a `<id>.v1.json` file the
   index lists. Any other name, subdirectory, symlink, or unreadable/malformed JSON is a failure, so
   a stray private file cannot sit in a served directory unchecked.

The validator never raises: malformed input of any shape is reported as a failure string.

## Not claimed

The route fields are plain documented credit paths. They do not claim influence, friendship or
intent, and the builder's route is not the site's ranked recommended route (ADR 0059).
