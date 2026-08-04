# ADR 0055: igraph for offline research graph analytics

- **Status:** Accepted
- **Date:** 2026-08-04
- **Depends on:** [ADR 0054](0054-research-lane-and-promotion-boundary.md), [ADR 0018](0018-benchmark-results-local-only.md)

## Context

`docs/ROADMAP.md` section 7 has stood open since Phase 1: "compare compact
arrays with at least one optimized graph library... select the production
representation only after measurement." Phase 2 measured the browser-local
CSR representation against nothing but itself (ADR 0050); Phase 3's
research platform needs real offline graph analytics — connected
components, community detection, bridge-contributor ranking — that
neither `graph.py`'s DuckDB-backed `CreditGraph` nor
`compact_graph_bench.py`'s browser-pathfinding CSR provide today. This is
the first real measurement against actual general-purpose graph libraries,
closing the roadmap item.

Three candidates were benchmarked at the real scope this platform runs at
— a bounded topic corpus (Jamiroquai's real 1-hop corpus, hundreds of
nodes), not the full canonical dataset — using real co-credit edges loaded
via `graph.py`'s own public `credit_edges_sql`, per
`docs/RESEARCH_GRAPH_BENCHMARK_METHOD.md`.

## Decision

**igraph is the primary library for offline research graph analytics**
(`packages/research/.../graph_bench.py`, and the primitives Slice D
builds on top of it). Real measured results at topic-corpus scale:

- All three libraries (NetworkX, igraph, rustworkx) agreed exactly on
  node/edge/component counts on both a synthetic correctness fixture and
  the real Jamiroquai corpus — a real cross-library correctness proof, not
  three independent, unverified timing runs.
- igraph was dramatically faster than NetworkX for both construction and
  community detection (tens of times faster for each, real hardware
  numbers in `local/benchmarks/` only), with substantially less peak
  memory.
- rustworkx's construction speed sat between the two, but it has no
  built-in community-detection algorithm as of this pass, so it can't
  serve that specific planned workload (community detection is one of
  Jamiroquai analysis's four core questions — Slice D) without an
  additional dependency or a hand-rolled implementation.

**NetworkX stays available** as the readable correctness baseline for
tests (`test_graph_bench.py`'s hand-computable fixtures) and any future
workload igraph doesn't cover cleanly — not removed, just not primary.

**rustworkx is not adopted** at this time — its construction-speed
advantage over NetworkX doesn't offset lacking community detection, given
igraph already covers both the speed and the algorithm need. This can be
revisited if a future workload specifically needs Rust-level performance
igraph can't match, or if igraph gains a real installation/maintenance
problem on some future hardware class.

**Scope stays bounded**: this decision is for *offline analytics over a
bounded topic corpus*, never a replacement for `graph.py`'s production
DuckDB-backed evidence-resolution path or `compact_graph_bench.py`'s
browser-pathfinding CSR — those answer "how does A connect to B" and stay
exactly as they are. igraph answers a different question, "what structure
exists in this network," that neither of the existing representations
was built to answer.

**All three libraries install via prebuilt wheels** on this hardware — a
real, confirmed zero-native-build-risk result (relevant since Slice C's
own stop condition was "if a benchmarked graph library fails to build
cleanly, fall back to NetworkX and move on" — that fallback was not
needed).

## Consequences

- `networkx`/`python-igraph`/`rustworkx` are dependencies of
  `packages/research`'s optional `graph` extra only (`uv sync --package
  networked-players-research --extra graph`) — not the base install, and
  not a dependency of `networked-players-catalog`/`graph-core` at all.
  `apps/web`'s public product is entirely unaffected.
- `packages/research/tests/test_graph_bench.py` skips cleanly
  (`pytest.importorskip`) if the `graph` extra isn't installed, but CI
  installs it so the correctness fixtures actually run on every PR, not
  silently skip.
- Slice D's community-detection and bridge-analysis primitives build on
  igraph's real API (`community_leiden`, `connected_components`), not a
  library-agnostic abstraction layer — premature abstraction was judged
  not worth it for a single, clearly-won candidate.

## Revisit trigger

If a future workload needs rustworkx's Rust-level performance specifically
(e.g. a topic corpus scaling to a size where igraph's C implementation
becomes the bottleneck), re-benchmark at that real scale before switching
— don't assume today's small-scope result generalizes upward without
re-measuring, per this project's own "measure before optimizing"
discipline.
