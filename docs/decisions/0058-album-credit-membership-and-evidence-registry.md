# ADR 0058: Album-credit membership, evidence-release registry, and record-to-record pathfinding

- **Status:** Accepted
- **Date:** 2026-08-07
- **Depends on:** [ADR 0038](0038-hybrid-album-catalog-assembly.md), [ADR 0043](0043-connection-guesser-corrective-slice.md), [ADR 0048](0048-contributor-index-and-pages.md), [ADR 0050](0050-browser-pathfinding-architecture-selection.md), [ADR 0051](0051-connect-two-records.md)

## Context

Connect Two Records (ADR 0051) resolves each selected album down to its
single primary `artist_id` and searches artist-to-artist — no album's
actual personnel is ever consulted, and results render a bare
`Release #12345 on Discogs` link. This was a deliberate, named simplification
at the time (ADR 0051's own text: "does not reuse `EvidencePanel`... a
future slice could add full evidence"). This ADR is that slice, and closes
a second, more structural problem discovered while designing it.

**"Who's credited on album X" is currently answered three different,
disagreeing ways** across the artifacts that all claim to derive from the
same `catalog_version`:

- `challenge.v2.json` traverses `credit_edges` (the traversal denylist
  only, no performer-role check).
- Connection Guesser / Record Routes traverse `credit_edges`, then
  additionally filter each hop through the fail-closed `is_performer_role`
  allowlist.
- `pathfinding_graph.py` traverses `credit_edges` scoped to each catalog
  artist's full ego network — not to any specific album's
  `main_release_id` at all, so a node's edges can come from *any* release
  that artist appears on anywhere in the one-hop corpus.
- `contributor_index.py` doesn't query the graph at all; it re-aggregates
  whichever hops happen to already exist in the other artifacts.

Real, measured consequence: the "how many contributor identities does the
public catalog have" question has three different real answers today —
549 (`contributors/index.v1.json`), 1,904 (`game/universe.v1.json`), and
36,819 (the pathfinding graph's total node count, a much broader ego
network than the 140-album catalog). None of these is wrong on its own
terms; they're just answering different, unreconciled questions.

## Decision

**Three artifacts, one coherent change, shipped together:**

1. **`album-credit-membership.v1.json`** — for each of the 140 catalog
   albums, the definitive list of contributors credited on that album's
   existing `main_release_id` (the same release `assemble_album_catalog`
   already chose — never re-derived). This becomes the single canonical
   answer to "who's credited on album X." It does not replace the
   traversal denylist or the game-round allowlist — both keep governing
   what they already govern — it only ends the inconsistency in *album
   membership specifically*.
2. **`evidence-release-registry.v1.json`** — a deduplicated,
   parallel-array registry of every release id that can appear as evidence
   anywhere in the product: the union of `challenge.v2.json`'s releases,
   `routes/rounds.v1.json`'s releases, and every distinct
   `evidence_release_ids` entry in the pathfinding graph. Measured real
   union size: **17,895** distinct release ids — an order of magnitude
   past the ~432/326 already covered by the first two sources alone,
   because the pathfinding graph's broader ego network reaches releases
   neither of those artifacts ever needed to describe before. Each entry
   carries title/year/country/`master_id`/source URL, and a hotlinked
   cover-art URL only where the release is a catalog album's own
   `main_release_id` and that album already has an `album-art.v1.json`
   entry — no new Discogs calls, no rehosting, honestly `null` everywhere
   else. Shipped as parallel arrays (`release_ids`, `titles`, `years`, …),
   not an array of per-release objects — at this scale (two orders of
   magnitude past `contributor-index`'s 549 entries, closer to the CSR
   graph's own scale) ADR 0050's own measured lesson applies: object-array
   JSON gzips far larger than parallel arrays at this size.
3. **Virtual album-anchor nodes, `pathfinding/graph.v2.json`** — one
   synthetic node per catalog album (negative `virtual_artist_id`,
   explicitly validated disjoint from real positive Discogs ids), bidirectionally
   zero-cost-edge-connected to every one of that album's real credited
   contributors already present in the bounded ego network. A
   record-to-record search becomes an ordinary single-source/single-sink
   BFS between two virtual nodes — `findPath`/`bfs_over_csr`'s core loop
   needs **zero changes**, only graph construction changes. New top-level
   field `album_virtual_nodes` gives the frontend an explicit
   `album_id → node` map. Ships as a new file (`schema_version: 2`), not a
   silent field-add to `graph.v1.json` — the existing validator already
   enforces an exact top-level key set, so this is a breaking shape change
   by that rule regardless, matching the `challenge.v1` → `challenge.v2`
   precedent. `graph.v1.json` stays live and unedited until Connect Two
   Records actually cuts over to `graph.v2.json`; retirement of v1 is an
   explicit, separate step once that cutover lands, not silent.

**A fourth, smaller fix ships alongside these**: `pathfinding_graph.py`'s
per-edge role text was a single, 60-character-truncated "representative
role" (first non-null role found for an `(artist_id, release_id)` pair).
Fixed in place — join every distinct role found for that pair, no
truncation — rather than joining role text from the new evidence registry,
which deliberately carries release metadata only (title/year/source), not
per-credit role text; extending it to also carry role text would mean
re-deriving a second, ~17,895-release-scoped credit table, real scope
creep past what the registry is for.

**What does not change**: ADR 0050's bounded ego-network scope (real,
non-catalog contributors remain valid intermediate hops — only the two
search *endpoints* are now anchored to real album personnel instead of one
primary artist); the three-layer role model (denylist / allowlist / role
taxonomy display layer) stays exactly as ADR 0035/0039/0047 established —
none of these three artifacts touches `_NON_COLLABORATIVE_ROLE_TOKENS`.

## Consequences

- Connect Two Records can now genuinely claim "record-to-record": every
  route's two endpoints are real people credited on the two selected
  albums' own accepted releases, not a stand-in primary artist.
- Every hop and both endpoints can render a real evidence card (title,
  year, cover, source link) instead of a bare release id.
- The "who's credited on album X" question now has one canonical answer
  for the 140-album catalog; the broader ego-network / game-universe
  counts (1,904 / 36,819) remain real and meaningful for their own
  purposes (exploration reach, game-round pools) — this ADR does not
  collapse them into one number, it only adds the missing canonical
  answer for the catalog-membership question specifically.
- `evidence-release-registry.v1.json` is a materially larger public
  artifact than any existing metadata-only artifact; its real gzip size
  must be measured (not estimated) at build time and flagged for review if
  it approaches the pathfinding graph's own ~1.8MB budget.
- Two live pathfinding-graph generators (v1, v2) coexist for the duration
  of the Connect Two Records cutover — a deliberate, bounded transition
  window, not a permanent state.

## Validation

`packages/graph-core/tests/test_album_credit_membership.py`,
`test_evidence_release_registry.py`, and the extended
`test_pathfinding_graph.py` (role-text join, virtual-node disjointness,
sentinel-role placement, isolated-virtual-node no-crash case) cover the
Python side. `packages/contracts/tests/test_album_credit_membership_contracts.py`
and `test_evidence_release_registry_contracts.py` cover the new
dependency-free validators. `apps/web/tests/pathfinding-bfs-v2.spec.ts` and
`pathfinding-bfs-parity-v2.spec.ts` cover the TypeScript BFS wrapper
(`findAlbumRoute`) and extend the existing manually-pinned parity pattern
to the new virtual-node code path. `apps/web/tests/game-connect-endpoints.spec.ts`
and the extended `game-connect.spec.ts` cover the rendered product surface,
including a direct regression guard on the "more musical route" duplicate-
render bug this same phase fixes.

## Revisit trigger

If `evidence-release-registry.v1.json`'s real measured gzip size, once
built in the slice that follows this ADR, meaningfully exceeds the
pathfinding graph's own ~1.8MB budget, revisit its shape (e.g. splitting
metadata the browser needs immediately from a lazily-fetched detail tier)
before publishing it as-is — this ADR's parallel-array decision is the
first mitigation, not a guarantee the result fits the same budget.
Separately: this ADR does not close the pre-existing "no automated
cross-language BFS parity harness" gap named in ADR 0051's own Revisit
trigger — it only extends that same manually-pinned pattern to cover the
new virtual-node code path. That gap remains open for whichever future
work actually builds a shared dual-runner.

**Addendum (Slice 4):** the pathfinding graph's own budget referenced
above was itself re-measured in this same phase (see ADR 0051's Slice-4
addendum) — fixing a real per-edge role-text truncation defect changed its
real size from ~1.8MB to **~2.26MB gzip**. `evidence-release-registry.v1.json`'s
real measured 354KB gzip (Slice 3) stays comfortably under either figure —
no revisit needed on that account.
