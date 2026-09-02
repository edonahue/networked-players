# Pathfinding graph contract (pathfinding-graph-v3)

The public pathfinding graph
(`apps/web/public/data/pathfinding/graph.v3.json`), produced by
`networked-players-catalog build-pathfinding-graph` and validated by
`validate-pathfinding-graph` /
`networked_players_contracts.pathfinding_graph::pathfinding_graph_failures`
(ADR 0050/0051/0058/0068).

> **v3 gates every edge on documented performance, not merely a shared
> credit.** Everything `pathfinding-graph-v2.md` says about the parallel-array
> CSR shape and virtual album-anchor nodes still holds byte-for-byte — v3 is
> the identical shape, built from a narrower edge relation. A real edge
> (`credit_edges`, via `graph.py`'s `credit_edges_sql`) now requires the
> non-anchor side of `same_recording`/`release_scope` to pass
> `eligibility.py`'s `is_performer_role` when its `credit_scope` is
> `track_credit`/`release_credit`; `track_artist`/`release_artist` billing
> stays always-eligible regardless of role text, the same rule that keeps a
> billed artist connected to their own record. A virtual album-anchor edge
> (`edge_eligible_membership_artist_ids`) gets the identical
> `credit_scope`-aware gate. See ADR 0068 for the full policy and its
> real-corpus audit.

## What changed from v2

Every v2 field keeps its exact same meaning and the CSR/`album_virtual_nodes`
shape is unchanged. v3 adds exactly one new top-level field:

| Field | Type | Meaning |
| --- | --- | --- |
| `graph_policy_version` | int, >= 1 | Which `graph.py.GRAPH_POLICY_VERSION` produced this graph's edges. Currently 1 (ADR 0068's performer gate). Included in the `pathfinding_graph_version` content hash, so two graphs built under different policy versions can never collide on the same hash even if their edge sets happened to coincide. |

No other field changes shape or meaning. This is a policy change, not a
structural one — the same reason `challenge-v2.md` also gained a
`graph_policy_version` field without a schema-version bump of its own; here
the pathfinding graph's schema version bumps anyway because its validator
already had schema-version-aware dispatch infrastructure from the v1→v2
transition, and the field addition is the natural place to exercise it
again.

## Real measured effect (2026-09-01, `discogs-onehop-v4`, `snapshot=20260601`)

| Metric | v2 (broad) | v3 (performer-gated) | Change |
| --- | --- | --- | --- |
| Nodes | 41,736 | 20,845 | −50.0% |
| Directed edges (`neighbors` length) | 151,726 | 76,646 | −49.5% |
| `album_virtual_nodes` | 179 | 179 | unchanged |
| Isolated album anchors (zero real neighbors) | 0 | 0 | unchanged |
| Connected components | 1 | 1 | unchanged |
| Catalog albums in the (single) largest component | 179 / 179 | 179 / 179 | unchanged |

Every one of the 179 real catalog albums keeps at least one real,
performer-qualifying credited contributor and remains in the single
connected component both before and after — zero newly-isolated albums.
Full detail: `docs/PERFORMER_GRAPH_ARTIFACT_MIGRATION_REPORT.md`.

## Validation

`pathfinding_graph_failures(graph, catalog)` runs every v2 check unchanged
(structural CSR invariants, `catalog_version` agreement, version
recomputation, `album_virtual_nodes` catalog-coverage/sentinel-placement)
plus, when `schema_version == 3`: `graph_policy_version` is a positive
integer.

## Status: the only published pathfinding graph

`graph.v3.json` shipped dual-live alongside the byte-unedited
`graph.v2.json`, with both registered in `PUBLIC_ARTIFACT_GROUPS` and
validated by `make check` for the duration of that window. Connect Two
Records and Network Explorer cut over to it, followed by the private
research workbench and the fleet artifact-check default — every consumer
identified by the same grep-based audit `pathfinding-graph-v1.md`'s own
retirement note describes. `graph.v2.json` was then deleted as an explicit,
separate step, and the two registered groups collapsed into one,
`pathfinding_graph`. `data/contracts/pathfinding-graph-v2.md` was removed
with it; `pathfinding_graph_failures` still accepts v1- and v2-shaped
payloads, since the validator never narrowed — only the published artifact
set did.

## Revisit trigger

`pathfinding-graph-v2.md`'s own revisit trigger anticipated a v3 for a
different reason (weighting virtual-node edges by credit prominence) — that
has not happened; this v3 exists for ADR 0068's performer gate instead. If
a future change also needs edge weighting, or `eligibility.py`'s token set
changes in a way that itself needs its own graph-construction-rule version
(not just a config-only token addition, which does not bump
`GRAPH_POLICY_VERSION`), extend this contract explicitly or add a
clearly-named `v4`.
