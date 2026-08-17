# ADR 0063: `bridge_analysis` (betweenness) promotion — measured and rejected

- **Status:** Accepted
- **Date:** 2026-08-17
- **Depends on:** [ADR 0054](0054-research-lane-and-promotion-boundary.md) (the promotion boundary this decision applies), [ADR 0055](0055-research-graph-library-selection.md) (igraph's scope, which this ADR does not change), [ADR 0059](0059-recommended-route-selection.md), [ADR 0060](0060-interesting-next-step-signal.md) (both already rejected raw-degree/hub bias — this decision extends the same discipline)

## Context

`docs/NEXT_PATH_BRIEF.md`'s "Most-connected-contributors view" entry has
stood open since the post-Phase-3 cleanup pass, naming two things: a raw
co-credit-degree view, and a richer signal beyond raw degree ("a second,
simpler, complementary lens on contributor connectivity alongside the
existing betweenness-based 'bridge contributors' signal").

**Half of this was already resolved before this pass.** `/contributors/`
already ships a "most connected" view (ADR 0058 Slice 8,
`apps/web/src/game/contributorsDirectory.ts`'s `mostConnected()`), built
entirely from the already-published `connection_count` field
(`packages/graph-core/src/networked_players_graph_core/contributor_index.py:299`)
— zero new backend, zero research-lane dependency.

**What remained open**: whether `packages/research/src/networked_players_research/graph_analysis.py`'s
`bridge_analysis()` (betweenness centrality — "contributors whose removal
would most fragment the network," ranking the top `N` by betweenness score)
should be promoted from the research lane (ADR 0054) to a real public
feature. The entry's own "biggest uncertainty" was *"whether this belongs on
the existing Network Explorer or as a new view."*

Real investigation answered that surface question — the Network Explorer's
entire rendering model is one-center-plus-neighbor-circle
(`apps/web/src/game/explorerStage.ts`), structurally the wrong host for a
global ranked list; `/contributors/`'s directory (already list-shaped,
already sorts by a connectivity metric) is the natural fit. But real,
fresh measurement against the actual published production graph — run
this pass — found something that makes the surface question moot: **the
underlying signal doesn't hold up against the real data.**

### The measurement

Run directly against the real, already-public
`apps/web/public/data/pathfinding/graph.v2.json` (36,959 nodes including
140 virtual album-anchor nodes, 65,133 real undirected edges after CSR
deduplication) — no private data involved, via `packages/research`'s
existing optional `graph` extra (`uv run --package
networked-players-research --extra graph`), on this machine:

1. **`igraph.Graph.betweenness()` over the full graph took 1,263.8 seconds
   (~21 minutes)**, single real run. This is the first production-scale
   measurement of anything from `packages/research`'s graph tooling — ADR
   0055 benchmarked only at topic-corpus scale (~656 nodes for Jamiroquai)
   and explicitly flagged that its results shouldn't be assumed to
   generalize upward without re-measuring. This is that re-measurement, at
   ~56x the node count and ~93x the edge count ADR 0055 actually tested.
   Not prohibitive for an offline batch step by itself, but real, and it
   would require adding `igraph` — a C-extension — as a *production*
   dependency of `graph-core`/`catalog`, reversing ADR 0055's explicit
   scoping that igraph is "not a dependency of
   `networked-players-catalog`/`graph-core` at all... `apps/web`'s public
   product is entirely unaffected."
2. **The decisive finding, checked first because it's cheaper and more
   directly on-point**: real cut vertices (`igraph.Graph.articulation_points()`,
   0.05 seconds) — 140 exist in the graph. For **every single one**, deleting
   it and measuring the resulting connected components
   (`graph.connected_components()`, 6.7 seconds total for all 140) shows the
   second-largest resulting component has size **exactly 1, in all 140
   cases, no exceptions**. The graph is one dense, small-world-connected
   36,819-node component with a sparse fringe of degree-1 leaf artists —
   there is **no real multi-node "bridge" structure in it at all**. The
   highest-degree cut vertices are exactly the most famous artists in the
   catalog (Elvis Presley — degree 1,696, sheds 1,177 leaf nodes on
   removal; Elton John, Miles Davis, David Bowie, Eric Clapton, Bob Dylan,
   The Rolling Stones, Herbie Hancock, Sting, Michael Jackson, Paul
   McCartney, The Beatles, and so on down the list — all shed only
   single-node leaf fragments).

`bridge_analysis()`'s own docstring frames its output as ranking
"contributors whose removal would most fragment the network." The
cut-vertex measurement tests that claim directly, over the real graph, and
finds it false in every case that could show it true: "removal fragments
the network" only ever manifests here as "a famous hub sheds a handful of
obscure leaf collaborators" — never as "this contributor connects two
otherwise-separate communities." Betweenness centrality, mathematically a
continuous generalization of cut-vertex centrality, would almost certainly
reproduce the same fame-correlated ranking over this same structure — there
is no genuine community separation in the graph for it to rank.

## Decision

**Do not promote `bridge_analysis()`/betweenness centrality to a public
production feature.** This is a measured, closed **no** — not a deferral
pending more measurement (contrast ADR 0061/0062, which deferred pending a
future trigger). The real graph structure itself doesn't support the
signal's premise: a "bridge contributors" feature built from this data
would, in practice, just be an expensive (~21 minutes), dependency-heavy
(new production igraph dependency) way to re-rank contributors by fame —
redundant with, and strictly worse than, the already-published
`connection_count` raw-degree signal. This is exactly the hub-bias failure
mode ADR 0059 (Connect's old route scorer) and ADR 0060
(`interesting_next_step`'s explicit anti-hub tie-break) already identified
and designed around; this decision extends the same discipline to a third
signal before it ships, rather than after.

**`community_detection()` (Leiden modularity clustering) is explicitly
untouched by this decision.** It asks a structurally different question —
sub-community clustering *within* one connected graph, not hard
multi-node separation — that the cut-vertex finding above does not test
and does not settle. It remains exactly as open as it was before this
pass; nothing here should be read as a finding against it.

**Close `docs/NEXT_PATH_BRIEF.md`'s "Most-connected-contributors view"
entry as resolved**, not left open indefinitely: raw degree already
shipped (no gap), and the richer signal was investigated on real data and
found not to deliver value. A genuine close, not another deferral.

## Consequences

- No code, dependency, artifact, contract, or UI change. `packages/research`'s
  `graph_analysis.py` is untouched; ADR 0055's scoping of igraph to the
  research lane's optional `graph` extra stands unchanged.
- `docs/NEXT_PATH_BRIEF.md`'s "Most-connected-contributors view" entry is
  marked resolved with a pointer to this ADR; `community_detection`'s
  promotion question is named separately so it isn't silently swept into
  this closure.
- A future contributor asking "should we promote bridge_analysis" again can
  start from this ADR's real measurements rather than re-deriving them or
  re-running a 21-minute benchmark.

## Validation

No new runtime code — this ADR's claims are themselves the validation. The
measurements above are reproducible: `apps/web/public/data/pathfinding/graph.v2.json`
is a committed, real artifact; the commands run were `igraph.Graph.betweenness()`,
`igraph.Graph.articulation_points()`, and `igraph.Graph.connected_components()`
after a component-vertex deletion, via `uv run --package
networked-players-research --extra graph python3`, no private data or
research-lane corpus involved.

## Revisit trigger

Re-open this decision if either becomes true:

1. A future catalog snapshot's real cut-vertex check (the same cheap,
   0.05-second `articulation_points()` measurement run here) shows genuine
   multi-node separators exist — i.e., the graph's topology has changed
   enough that "bridge" stops being synonymous with "famous hub shedding
   leaves." Re-run the check before assuming; don't extrapolate from this
   snapshot indefinitely.
2. A differently-scoped signal is proposed that doesn't depend on hard
   graph separation — e.g. `community_detection()`/Leiden-based
   within-cluster findings, or a role/genre-based clustering question —
   since that question is untouched by this decision and would need its
   own real measurement, not an inference from this ADR.
