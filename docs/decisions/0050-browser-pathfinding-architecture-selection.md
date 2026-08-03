# ADR 0050: Browser-local, bounded-scope pathfinding for Connect Two Records

- **Status:** Accepted
- **Date:** 2026-08-03
- **Depends on:** [ADR 0049](0049-exploration-tier-policy-and-versioning.md)
- **Method:** [docs/GRAPH_BENCHMARK_METHOD.md](../GRAPH_BENCHMARK_METHOD.md)

## Context

Connect Two Records (Slice F) needs a pathfinding architecture. Three
candidates were on the table: fully browser-local search over a compact
graph, a DuckDB-WASM materialized graph, or a bounded Cloudflare Worker. The
project's own principle is measure before optimizing — none should be chosen
without real evidence.

`packages/graph-core/.../compact_graph_bench.py` (a CSR adjacency + BFS,
proven to agree with `CreditGraph.find_path` on a synthetic fixture) was
built and measured against real one-hop-corpus data at four seed scopes: the
current 140-album catalog's 1-hop neighborhood, a candidate 500-album
tier's (ADR 0049) 1-hop and 2-hop neighborhoods, and an attempted full-corpus
build.

## Decision

**Browser-local CSR search is viable, but only at a small, deliberately
bounded scope — not the full one-hop corpus, and not an unrestricted
multi-hop expansion from a several-hundred-album seed set.**

The measured evidence (`docs/GRAPH_BENCHMARK_METHOD.md`): the 140-album
catalog's 1-hop ego network compresses smaller than the largest artifact
already shipped today, with parse and per-query BFS latency both fast even
under simulated low-end-mobile CPU throttling. The 500-album tier's 1-hop
network is measurably larger but still plausible. Its 2-hop network,
however, balloons by an order of magnitude and already touches a large
majority of the *entire* one-hop corpus's edges — meaning there is no
comfortable "medium" scope between a small bounded neighborhood and
effectively the whole graph. The corpus is dense enough that hop-count alone
does not gracefully bound payload size once the seed set grows past a
few hundred artists.

**Concrete consequence for Slice F**: build Connect Two Records against a
browser-local CSR payload scoped to a 1-hop neighborhood no larger than
roughly the measured 140-to-500-album range, not against the full one-hop
corpus and not against a multi-hop expansion from a large seed set. If a
future exploration tier (ADR 0049) needs genuinely larger or multi-hop
reach, the fan-out itself must be bounded per-node (a per-artist degree cap,
mirroring `CreditGraph.find_path`'s existing `max_frontier_expansion`
concept), not just the hop count — this is an explicit revisit trigger, not
a decision made now.

DuckDB-WASM and a bounded Cloudflare Worker were not implemented or measured
in this pass. Both remain legitimate fallbacks if a future, larger
exploration tier needs reach this architecture cannot cover — they are not
rejected, only not yet needed given the evidence for the scope Slice F
actually targets.

## Consequences

- Slice F's first version is scoped conservatively (comparable to today's
  140-album catalog, or a modestly larger bounded tier), which keeps the
  static-first, no-required-backend guarantee intact with real measured
  headroom, not an optimistic guess.
- The 2-hop/500-seed finding is a real constraint on Slice D's exploration
  tier ambitions: growing the *exploration* graph (for browsing, contributor
  discovery) does not automatically mean the *pathfinding* graph can grow
  the same way — the two may need different scopes, tracked separately by
  `catalog_version`/`exploration_corpus_version`/a future pathfinding-corpus
  version, per ADR 0049's namespace discipline.
- Real byte counts, timings, and the benchmark harness's raw output stay in
  `local/benchmarks/` (gitignored) and are never transcribed into a public
  doc with specific figures, per ADR 0018.

## Validation

`packages/graph-core/tests/test_compact_graph_bench.py`: CSR/BFS parity with
`CreditGraph.find_path` (both found-path and confirmed-no-path cases),
`FrontierTooLargeBench` raised (never silently returned as no-path),
deterministic construction regardless of edge order, and payload-size
scaling sanity. Real measurement was run via
`local/experiments/graph-benchmark/` against the actual one-hop dataset
(not committed — a one-off driver, not a supported package) and the current
committed 140-album catalog and Slice D's 500-album tier artifact.

## Revisit trigger

Revisit if: Slice F's real, shipped payload at the chosen scope exceeds a
size budget set once Brotli compression is actually measured (not yet done
— see the method doc's follow-ups); a future exploration tier needs
pathfinding reach beyond a bounded 1-hop neighborhood (requires a per-node
fan-out cap, not just a hop-count increase, per the finding above); or
DuckDB-WASM/a bounded Worker are later measured and found to clear a
meaningfully larger scope than browser-local CSR can — any of these would
warrant a new ADR, not a silent architecture change.
