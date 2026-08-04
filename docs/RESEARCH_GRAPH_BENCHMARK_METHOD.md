# Research graph-library benchmark method (Phase 3 Slice C)

Closes `docs/ROADMAP.md` section 7's open item ("compare compact arrays
with at least one optimized graph library"). Decides which library (if
any) powers offline graph analytics for the research platform — components,
communities, bridge-contributor ranking — over a bounded topic corpus.
Real measured numbers on real hardware are never published here (ADR
0018) — this document is the reproducible methodology and the resulting
decision; real timings/memory live in `local/benchmarks/` (gitignored).
See `docs/decisions/0055-research-graph-library-selection.md` for the
outcome this method produced.

## What's measured, and how

**Representation**: `packages/research/.../graph_bench.py`'s `load_edges`
loads real `(artist_a_id, artist_b_id, release_id)` co-credit edges for a
built topic corpus via `graph.py`'s own public `credit_edges_sql` — the
exact same edge semantics (`same_recording`/`co_performers`/
`release_scope`, placeholder and compilation guards) the production game
traversal uses, never a simplified re-derivation. A correctness fixture
(`test_load_edges_uses_the_real_credit_edges_sql_semantics`) proves this:
a DJ-compilation-shaped release with many track-scope credits and no
shared `track_index` produces zero edges, not the giant clique a naive
"shared `release_id`" join would produce — the exact hub bug
`credit_edges_sql`'s own docstring names.

**Candidates**: the existing DuckDB-backed `CreditGraph`/CSR
representations (unchanged — `graph.py`'s production traversal path,
`compact_graph_bench.py`'s browser-pathfinding CSR) are the baseline; three
general-purpose graph libraries were newly benchmarked:

- **NetworkX** — pure Python, the readable/correctness baseline.
- **python-igraph** — C-backed, with built-in Leiden-style community
  detection (`community_leiden`).
- **rustworkx** — Rust-backed via prebuilt wheels (no compiler needed on
  this hardware — confirmed: all three installed from wheels, zero
  native-build risk), no built-in community detection as of this pass.

**Scope measured**: a real built topic corpus at Jamiroquai's own 1-hop
scope (the actual Slice B/D dogfood case) — hundreds of nodes, low
thousands of edges, the real scale this platform's analyses run at. Not
full-corpus scale, which the Phase 2 CSR benchmark already found
infeasible for a from-scratch Python build and isn't this benchmark's
goal either — offline analytics here are always over a *bounded* topic
corpus, never the full canonical dataset.

**What's recorded per library**: node/edge count (must agree across every
library and against `load_edges`'s own raw/deduplicated counts — a
correctness check, not just a timing one), construction time, peak traced
memory (`tracemalloc`), connected-component count and largest-component
size, and community-detection time/count where the library supports it
(`None`, not a substituted algorithm, where it doesn't — rustworkx is
reported honestly as "unavailable" for community detection in this pass,
never silently swapped for a different metric).

**Correctness fixtures**: a small, hand-computable synthetic graph (two
disconnected triangles — 6 nodes, 6 edges, 2 components of size 3 each)
gets the identical component-structure answer from every library
(`test_all_three_libraries_agree_on_component_structure`), proving the
three implementations agree before trusting any of them on real data.

## Decision framework

Not "which library is fastest" in the abstract — which library best serves
the actual planned workloads (components, community detection, bridge-
contributor ranking) at the actual scope this platform runs at (a bounded
topic corpus, not the full canonical dataset), while staying a reasonable
dependency to add. A heterogeneous outcome (different libraries for
different jobs) is an acceptable, expected result — nothing here is
required to replace `graph.py`'s production evidence-resolution path or
`compact_graph_bench.py`'s browser-pathfinding CSR.

## Results (methodology only — see local/benchmarks/ for real figures)

Real byte/timing/memory figures on this lab's hardware stay in
`local/benchmarks/` per ADR 0018. Qualitative, order-of-magnitude
characterizations (not hardware-tied claims) are fine to report here,
matching `GRAPH_BENCHMARK_METHOD.md`'s own precedent:

- All three libraries agreed exactly on node count, edge count, component
  count, and largest-component size for both the synthetic correctness
  fixture and the real Jamiroquai topic corpus — a real cross-library
  correctness confirmation, not just three independent timing runs.
- **igraph was dramatically faster than NetworkX** for both graph
  construction and community detection at this scope — on the order of
  tens of times faster for each — while using substantially less peak
  memory.
- **rustworkx's construction was also fast** (between igraph's and
  NetworkX's), but it has no built-in community-detection algorithm as of
  this pass, so it cannot serve that specific planned workload without an
  additional dependency or a hand-rolled implementation.
- NetworkX remained the slowest and highest-memory of the three at this
  scope, consistent with it being a pure-Python implementation, though its
  absolute cost was still small in wall-clock terms for a bounded
  topic-corpus-sized graph (hundreds of nodes) — the gap would matter more
  at a larger scope than it does here.

## Conclusion this evidence supports

**igraph** is the primary library for offline graph analytics
(components, community detection, bridge-contributor ranking) over a
bounded topic corpus — it wins decisively on both speed and memory at the
real scope this platform runs at, and it's the only one of the three
candidates with built-in community detection. NetworkX stays available as
the readable correctness baseline for tests and for any future workload
igraph doesn't cover cleanly. rustworkx is not adopted for this platform
at this time — its construction speed doesn't offset the lack of
community detection given igraph already covers both needs. See ADR 0055
for the specific decision and its revisit trigger.

## What wasn't completed (explicit follow-ups)

- Betweenness/bridge-contributor-ranking timing was not separately
  benchmarked in this pass — Slice D's real bridge-analysis
  implementation is the next point to measure it, once there's a concrete
  workload shape to measure against.
- Subgraph extraction and serialization (both named as candidate
  workloads in the original Phase 3 plan) were not benchmarked — deferred
  until a real analysis needs them, per the plan's own "don't build it
  until a workload justifies it" discipline.
- DuckDB-vs-igraph timing was not directly compared for the specific
  operations both *can* do (e.g. degree) — the two answer genuinely
  different questions (evidence resolution vs. offline structural
  analysis) and aren't real substitutes for each other at this platform's
  current scope.
