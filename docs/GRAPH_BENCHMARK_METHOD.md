# Graph pathfinding benchmark method (Phase 2 Slice E)

Decides the architecture for Connect Two Records (Slice F) and, longer-term,
the Network Explorer (Slice G): fully browser-local pathfinding, a
DuckDB-WASM materialized graph, or a bounded Cloudflare Worker. Real measured
numbers on real hardware are never published here (ADR 0018) — this document
is the reproducible methodology and the resulting decision framework; real
results live in `local/benchmarks/` (gitignored). See
`docs/decisions/0050-browser-pathfinding-architecture-selection.md` for the
outcome this method produced.

## What's measured, and how

**Representation**: `packages/graph-core/.../compact_graph_bench.py` builds a
CSR (compressed sparse row) adjacency — sorted `artist_id` node array,
parallel `offsets`/`neighbors`/`evidence_release_ids` arrays (one release id
per edge, matching `graph.py`'s "single deterministic release evidences the
edge" semantic), serializable directly to fixed-width typed arrays
(`Int32Array` in a browser). `build_csr_adjacency` is deterministic regardless
of input edge order. `bfs_over_csr` mirrors `CreditGraph.find_path`'s exact
contract, including the inconclusive-vs-confirmed-no-path distinction
(`FrontierTooLargeBench`, never silently collapsed into "no connection").
Parity with the real DuckDB-backed graph is proven in
`packages/graph-core/tests/test_compact_graph_bench.py` on a synthetic
fixture.

**Candidate scopes measured**: run the reproducible harness in
`local/experiments/graph-benchmark/` (gitignored; not committed, since it's a
one-off driver script, not a supported package) against real one-hop-corpus
edge data, at these seed sets:

1. The current 140-album catalog's primary artists, 1-hop ego network.
2. Slice D's 500-album exploration tier's primary artists, 1-hop ego network.
3. The same 500-album seed set, 2-hop ego network.
4. The full one-hop corpus (attempted; see "what wasn't completed" below).

An "ego network" here means: seed artist set → every edge touching a seed or
a node reached from a seed within the stated hop radius → the induced CSR
graph over that touched edge set. This is the actual shape a bounded
browser-local search or a Network Explorer neighborhood would need, not an
arbitrary sample.

**What's recorded per scope**: node count, edge count, typed-array byte size,
raw JSON byte size, gzip byte size (Brotli was not measured in this pass —
see follow-ups), real in-browser parse time (`JSON.parse` + typed-array
construction, via a self-contained HTML page driven by Playwright — no
server needed), and BFS latency over a sample of real seed-artist pairs at
`max_hops=4` (matching the real product's default). Browser measurements ran
on both an unthrottled desktop Chromium context and a `Pixel 5` device
emulation profile, at three CPU throttle rates (1x/4x/6x via the Chrome
DevTools Protocol `Emulation.setCPUThrottlingRate`) as a phone-feasibility
proxy — Playwright's device emulation alone only changes viewport/UA/touch,
not CPU speed, so the throttled runs are the only ones that meaningfully
stand in for a real low-end phone.

## Decision framework

Three options, evaluated by the measurements above:

1. **Fully browser-local** — fetch a compact CSR payload once, BFS in JS,
   zero backend ever. Feasible only if the payload for the chosen graph
   scope clears a mobile-data-conscious size budget and parse+BFS time stays
   comfortably interactive even under CPU throttling. The scope choice
   matters enormously here — see results.
2. **DuckDB-WASM** — reuses `graph.py`'s exact SQL, at the cost of
   DuckDB-WASM's own fixed runtime bundle size (several MB before any data is
   even loaded, a well-documented characteristic of the library, not
   something this pass re-measured). Not implemented or measured in this
   pass — an explicit follow-up if option 1 proves too constrained at a
   useful scope.
3. **Bounded Cloudflare Worker** — server-side BFS over a small dataset baked
   into the Worker bundle at deploy time. Must never call back to the home
   fleet; must never become a required dependency for the static site's core
   experience (`apps/web/AGENTS.md`'s static-first rule). Not implemented in
   this pass — the fallback if neither 1 nor 2 clears a useful scope.

## Results (methodology only — see local/benchmarks/ for real figures)

Real byte counts, node/edge counts, and qualitative timing characterizations
are catalog-shape facts (like the project's already-public album/path/release
counts), not hardware-tied benchmark claims, so they're reported here at the
order-of-magnitude/qualitative level; precise millisecond timings on this
lab's specific hardware stay in `local/benchmarks/` per ADR 0018.

- The **140-album catalog's 1-hop ego network** is comfortably smaller than
  the largest artifact already shipped today (`routes/rounds.v1.json`,
  2.9 MB uncompressed) once gzip-compressed, with parse time in the tens of
  milliseconds and per-query BFS latency in the low single-digit
  milliseconds even on a throttled mobile CPU profile.
- The **500-album tier's 1-hop ego network** is measurably larger — roughly
  2-3x the 140-album scope's compressed size — while parse/BFS timing stayed
  fast in absolute terms even under throttling; size, not compute, is the
  binding constraint at this scope.
- The **500-album tier's 2-hop ego network** balloons dramatically — an
  order of magnitude larger than its own 1-hop network, and already touching
  a large majority of the entire one-hop corpus's total edge count. This is
  the single most important finding: the one-hop working set is dense enough
  that a 2-hop expansion from even a few hundred seed artists reaches nearly
  the whole graph. There is no comfortable "medium" tier between a small
  bounded 1-hop neighborhood and effectively the entire corpus.
- The **full one-hop corpus** CSR build was attempted directly (not
  extrapolated) but abandoned mid-run once it became clear it would not
  complete in a reasonable session time budget for this measurement pass —
  itself a data point: even *constructing* the full compact representation
  in pure Python at this scale is a real, nontrivial cost, separate from the
  question of whether the resulting payload would be downloadable at all.
  The 2-hop finding above makes a direct full-corpus measurement unlikely to
  change the conclusion.

## Conclusion this evidence supports

A fully browser-local, CSR-based architecture is genuinely viable **for a
small, deliberately bounded neighborhood comparable to the current 140-album
catalog's scope, or modestly larger** — not for the entire one-hop corpus,
and not for an unrestricted multi-hop expansion from a several-hundred-album
seed set. See ADR 0050 for the specific architectural decision and its
revisit triggers.

## What wasn't completed (explicit follow-ups)

- Brotli compression was not measured (only gzip) — Brotli typically
  compresses JSON further; re-measure before finalizing a specific payload
  budget.
- DuckDB-WASM and the bounded-Worker options were not implemented or
  measured at all in this pass.
- A properly-scoped "medium" tier (e.g., a few hundred seed artists at
  strictly 1-hop, or a curated 1.5-hop expansion that caps per-node fan-out)
  was not measured — the 500-seed 2-hop result suggests fan-out capping,
  not just hop-count capping, may be necessary for any tier between 140 and
  500 albums.
