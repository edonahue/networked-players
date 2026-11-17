# Playable-cohort contract (schema v2)

The playable pairs of a Collection: pairs of **catalog records** with a documented route between
them on the performer-only graph. Decision record:
[ADR 0074](../../docs/decisions/0074-collections-contracts.md). Validated by
`collection.py` as part of `collection_failures`; defined here separately from
[`collection-v1.md`](collection-v1.md), which carries the object.

## Why not a re-bind of v1

[`playable-cohort-v1`](playable-cohort-v1.md) is artist-to-artist over the one-hop corpus:
`release-...` ids, `hops[]` of `release_id` + two artists, quality flags, and a required
third-party `source_url` (ADR 0028). v2 has catalog `master-...` records as endpoints, routes
over the performer graph with the graph's own evidence ids, no third-party source requirement,
and the lineage inputs of a Collection. Different endpoints, different evidence model, different
rights posture: a new schema version, not a quiet change to v1. v1 and its synthetic example stay
as they are.

## Layout decision: embedded, not a sibling file

v2 lives **inside** the collection file as `playable_cohort`. A pair has no meaning outside its
collection, shares its lineage and version, and the page that plays pairs already loads the
collection file. A sibling file would double the loader's requests and let the two drift apart.
It stays a separately named contract so it can be split out later without changing pair shape.

## Shape

```json
"playable_cohort": {
  "schema_version": 2,
  "route_policy": "shortest-first-found-v1",
  "pairs": [
    {
      "record_a": "master-1",
      "record_b": "master-3",
      "hop_count": 1,
      "via": [11, 12],
      "via_names": ["Player 11", "Player 12"],
      "evidence_release_ids": [1002]
    }
  ]
}
```

- `record_a` precedes `record_b` in the collection's `records`; pairs are unique and ordered by
  `(index_a, index_b)`. The set may be a subset of all pairs (unreachable pairs are omitted).
- `via`, `via_names`, `evidence_release_ids`: exactly as a journey hop (see `collection-v1.md`):
  a path in `graph.v4` from one record's anchor to the other's, with the graph's own evidence id
  for every consecutive performer pair.
- `hop_count` = `len(via) - 1`, the number of performer-to-performer hops; `0` means one
  performer is credited on both records.
- `route_policy` is `shortest-first-found-v1`: a plain shortest path, first discovered in CSR node
  order over real performer nodes. **This is not the site's ranked recommended route** (ADR 0059,
  `recommendedRoute.ts`); there is no Python mirror of that ranking. Validation proves each route
  is a real documented path with the graph's evidence, not that it is the best one.

## Lineage

Same `provenance.inputs` as the collection (`catalog`, `pathfinding_graph`). A graph rebuild that
removes any pair's edge fails validation and names the pair; nothing silently re-routes.
