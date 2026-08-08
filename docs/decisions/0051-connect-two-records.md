# ADR 0051: Connect Two Records — the first search UI

- **Status:** Accepted
- **Date:** 2026-08-03
- **Depends on:** [ADR 0050](0050-browser-pathfinding-architecture-selection.md)

## Context

ADR 0050 measured browser-local CSR pathfinding as viable at a bounded scope
comparable to the current 140-album catalog. This ADR covers the actual
feature built on that architecture: the first search UI in the app (every
existing mode deals a pre-selected pair; nothing before this let a visitor
pick two arbitrary records themselves).

## Decision

**Backend**: `apps/web/public/data/pathfinding/graph.v1.json`
(`packages/graph-core/.../pathfinding_graph.py`, `data/contracts/
pathfinding-graph-v1.md`) — a CSR adjacency scoped to the 140-album
catalog's 1-hop ego network, with parallel-array names/edge-role evidence
(see ADR 0050's addendum for why: ~15x smaller gzip than an equivalent
array-of-objects shape). Real measured: 36,819 nodes, 60,696 edges, ~1.8 MB
gzip. Wired into `validate-public-artifacts`.

**Frontend**:
- `apps/web/src/game/pathfindingGraph.ts` — a TypeScript port of
  `compact_graph_bench.py`'s BFS (`bfsOverCsr`), kept in behavioral parity by
  manual inspection (both walk the same CSR arrays the same way; no shared
  test harness across languages exists yet — a real gap, see Revisit
  trigger). Returns hop objects or a typed failure reason
  (`"no-path"` | `"inconclusive"`), never collapsing the two.
- `apps/web/src/components/AlbumPicker.astro` + `apps/web/src/game/
  albumPicker.ts` — client-side substring filter over the pathfinding
  graph's own album scope (the 140-album catalog), no live search API (
  `apps/web/AGENTS.md`'s static-first rule).
- `apps/web/src/pages/play/connect/index.astro` — fits the existing
  `/play/<mode>/` namespace.
- `apps/web/src/game/routeQuality.ts` — a transparent secondary ranking
  ("more musical route") over the same BFS-found path, using Slice B's role
  categories (looked up via the contributor index, already published) and
  hub-degree penalties (`connection_count`, also from the contributor
  index). Never a new inferred edge — purely a presentation ordering over
  the same evidence, with an explicit, rendered explanation
  (`explainScore`), never a hidden score.
- Evidence rendering does **not** reuse `EvidencePanel`/`buildHopViews` —
  those need a full `Release` object (title, source_url, per-credit rows),
  which the pathfinding graph deliberately omits to stay compact (adding
  full release/credit objects for all ~61K edges would reintroduce the
  exact size problem the parallel-array design solved). Instead, a hop
  renders a lighter evidence line: both names, both roles
  (`edge_role_a`/`edge_role_b`), and a direct link to the real Discogs
  release page (`https://www.discogs.com/release/{release_id}`) as the
  source — still a real, verifiable, evidence-first link, just without the
  full per-track credit table other surfaces show. A future slice could add
  full evidence by fetching release detail lazily (only for the handful of
  hops actually found), rather than embedding it for every edge upfront.
- The fetched graph payload is cached in `sessionStorage` (not
  `localStorage` — large and disposable, unlike the persistent `np.game.v1`
  progression store), keyed by `pathfinding_graph_version`, invalidated on
  mismatch — the same pattern `dailyManifest.ts`/`routesResolver.ts` already
  established.
- Graceful failure: typed states (`fetch-failed`, `parse-failed`,
  `unknown-album` — an album outside the graph's scope, `inconclusive`,
  `no-path`) — the last two stay visibly distinct in the UI copy, matching
  `graph.py`'s own inconclusive-vs-no-path contract. The rest of the static
  site keeps working regardless of a failed search.

## Consequences

- This is the first feature where a user can select *any* two albums in
  scope, not a pre-curated pair — the UI must handle "no documented path"
  as a normal, expected outcome (most pairs of unrelated albums genuinely
  have none within a bounded hop count), not an error state.
- "More musical route" is copy-sensitive: it must read as "ranked by these
  transparent, evidence-only signals," never as a claim about which path is
  more real or more important. Enforced by the same `_FORBIDDEN_PHRASES`
  discipline other surfaces already use, extended to this page's copy.
- The pathfinding graph is scoped to the 140-album catalog specifically —
  if the catalog changes, the graph must be regenerated
  (`build-pathfinding-graph`) and its `catalog_version` will change,
  causing the frontend's session cache to invalidate naturally.

## Validation

`apps/web/tests/game-connect.spec.ts` (Playwright): a real found path
renders with evidence, dual ranking shown when they differ, an
inconclusive/no-path state renders distinctly, a fetch-failure state
degrades gracefully, and the session cache is reused across two searches.
`apps/web/tests/pathfinding-bfs.spec.ts` (pure-node): the TS BFS port's
correctness on a small fixture graph, mirroring
`test_compact_graph_bench.py`'s Python fixture cases.

## Revisit trigger

~~The Python (`compact_graph_bench.py`) and TypeScript (`pathfindingGraph.ts`)
BFS implementations currently have no shared, cross-language parity test —
unlike `canonical.py`/`canonical.ts`, which are proven byte-identical.~~
**Addendum (Phase 2 follow-up, Slice J):** closed, using the same pattern
`canonical.py`/`canonical.ts` already established — a manually-pinned
golden value, not an automated cross-runner harness. `apps/web/tests/
pathfinding-bfs-parity.spec.ts` runs a real `bfs_over_csr` invocation once
(the exact command is preserved as a comment in that file) and hardcodes
its output as TS assertions against `findPath` on the byte-identical CSR
fixture. This covers hop-list shape/values on a found path and no-path/
same-artist agreement. It does **not** cover: role text (Python's bench
module carries no `edge_role_a`/`edge_role_b` equivalent at all),
`findPath`'s `edgeFilter` parameter (no Python analog), or
`FrontierTooLargeBench`/`"inconclusive"` (Python signals this via a raised
exception, TS via a typed union member no code path produces today, since
this graph's bounded scope makes an in-memory BFS cheap regardless of
degree). If a future change makes `"inconclusive"` reachable in either
implementation, extend the parity test to cover it at that point.

**Addendum (Phase 4):** this ADR's own named gap — evidence rendering
skipping `EvidencePanel`/`buildHopViews` and the search resolving each
album to one primary `artist_id` rather than its real personnel — is
addressed by [ADR 0058](0058-album-credit-membership-and-evidence-registry.md),
which adds the album-credit-membership and evidence-release-registry
artifacts and a virtual-node search-endpoint mechanism on top of this
ADR's pathfinding architecture. See ADR 0058 for the current state of
both points.
