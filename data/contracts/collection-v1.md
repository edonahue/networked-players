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
| `generated_at` | string | A label; excluded from the content version. |
| `records` | string[] | Ordered catalog album ids (`master-...`); 4..24; distinct; **all in the catalog**; at least **3 distinct primary artists** (the E1 gate's qualifying-cluster rule). |
| `bridge_players` | object[] | 1..12 entries `{artist_id, name, records}`. `name` equals the graph's name. `records` lists at least 2 distinct records of the collection; the player must be **adjacent in `graph.v4` to each listed record's album anchor** (credited as a performer on it). |
| `journey` | object[], optional | Ordered hops (below). |
| `playable_cohort` | object, optional | `playable-cohort-v2` (see that contract). |
| `attribution` | `{label, source_url}`, optional | Only for a genuinely sourced theme; `source_url` is `https://`. |
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

### Provenance and version

- `provenance.inputs` declares exactly `catalog` and `pathfinding_graph`, each a content version
  string. Both must equal the current artifacts' versions (see ADR 0072 section 1 and
  `artifact-lineage-v1.md`); otherwise validation fails and the collection must be re-promoted
  and re-reviewed.
- `provenance.collection_version` = `collection-v1-` + `content_hash` (12 hex) of the collection
  with `provenance` and `generated_at` removed.

## Private-field guard

Validation fails if any key at any depth is `notes`, `note`, `review_note`, `reviewer`,
`reviewed_by`, `rejected`, `working_title`, `kept_records`, `input_hash`, `private`, or ends in
`_private`; if any string contains a forbidden substring (`/home/`, `data/private`, `local/`,
`DISCOGS_TOKEN`, `.ssh`); or if title, intro or attribution label contains a phrase that suggests
the owner's own collection (`my collection`, `my record`, `personal collection`, ...) or infers
influence or a working relationship from a shared credit (`worked with`, `collaborated with`,
`influenced`).

## Not claimed

The route fields are plain documented credit paths. They do not claim influence, friendship or
intent, and the builder's route is not the site's ranked recommended route (ADR 0059).
