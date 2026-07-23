# ADR 0046: Record Routes productionization

- **Status:** Accepted
- **Date:** 2026-07-22
- **Relates to:** ADR 0038 (hybrid album catalog), ADR 0043/0045 (canonical hashing, art registry), the post-Phase-1 plan (slice 6)

## Context

PR #43's ported backend (slice 1) already implemented a real, evidence-path
game mode — album A → artist X → album B (one hop) or through a hidden
middle-hop pair (two hops) — via `rounds.py`/`rounds_generator.py` and the
`build-rounds-from-dump` CLI command. This is a genuinely different question
from the flagship Connection Guesser's "name a performer credited on both
displayed albums" intersection semantic (ADR 0042), and was always intended
to become its own peer mode, **Record Routes**, once the shared real-data
architecture (canonical catalog, album-art registry) was live (which it now
is, per ADR 0044/0045 and the Phase 1 + art launch).

The legacy artifact this backend produces, however, has three gaps that make
it unsafe to ship as-is:

1. **Ordinal round ids** (`round-000001`) assigned by selection order — an
   unchanged round's id moves if the pool is regenerated or reordered, which
   is incompatible with any future frozen-schedule use (mirroring the exact
   problem corrective slice 4.5 found and fixed for the Connection Guesser).
2. **No `mode` field and no deterministic `artifact_version`** — the
   operator supplies `pool_version` by hand, and nothing distinguishes this
   contract from the Connection Guesser's at the JSON level (both artifact
   pairs have historically shipped as `universe.v1.json`/`rounds.v1.json`,
   in different directories — this is exactly the "ambiguous between Record
   Routes and Connection Guesser" trap already found once, ADR 0043 Finding 8).
3. **Embedded `cover_image`** on every album — mutable presentation data
   inside what would become a fingerprinted artifact, the same coupling ADR
   0045 removed from the Connection Guesser.

## Decision

Ship Record Routes as a genuinely distinct, production-safe artifact pair,
reusing the legacy backend's tested path *discovery* and *evidence assembly*
without inheriting its identity gaps.

- **New module** `networked_players_graph_core.record_routes` wraps
  `rounds_generator.generate_round_pool` (path discovery/scoring/diversity,
  unchanged) and `rounds.build_rounds_v1` (universe/evidence assembly,
  unchanged), then:
  - replaces every ordinal id with a **content-derived stable id**
    (`route-<hash>` of the sorted endpoints + ordered hop signatures);
  - computes **deterministic `pool_version`** (membership hash) and
    **`artifact_version`** (ordered complete-content hash), mirroring the
    Connection Guesser's ADR 0043/0045 identity model exactly;
  - sets an explicit **`mode: "record_routes"`** on both artifacts;
  - strips `cover_image` from every album (art-free, ADR 0045).
- **New artifact namespace**: `apps/web/public/data/routes/{universe,rounds}.v1.json`
  — never `apps/web/public/data/game/*`, never the Connection Guesser's daily
  manifest.
- **New dependency-free validator**
  (`networked_players_contracts.record_routes::record_routes_failures`,
  `data/contracts/record-routes-v1.md`) — its own key sets, its own `mode`
  check, its own id-recomputation, reusing the legacy contract's per-round/
  per-hop structural checks (`_hop_failures`, quality-flag validation) rather
  than duplicating them.
- **New CLI** `build-record-routes` / `validate-record-routes`.
  `build-rounds-from-dump` remains available (existing tests/tooling still use
  it) but its help text is corrected to say LEGACY/exploratory, mirroring the
  `build-album-catalog` vs `build-public-album-catalog` precedent (ADR 0038's
  corrective addendum).

Explicitly **not done**: merging or cherry-picking PR #43's plain frontend.
The Record Routes UI is built fresh in the current Astro design system
(`/play/routes/`), reusing `GameStage`/`EvidencePanel` patterns like every
other real surface.

## Consequences

- Record Routes and the Connection Guesser can never collide on disk or in a
  Pi validation job — different paths, different `mode`, different validator
  module name.
- A future frozen "Route of the Day" (if ever wanted) can reuse the exact
  `pool_version`/`artifact_version`/stable-id pattern already proven safe for
  the Connection Guesser's daily manifest, with no separate design needed.
- The one-hop/two-hop path *discovery* algorithm itself (candidate pairing,
  scoring, diversified selection) is unchanged and unaudited by this ADR — it
  was already real, evidence-preserving, and tested under PR #43/slice 1;
  this ADR only corrects identity and presentation-coupling gaps around it.
  Its **database-access pattern** did need a fix: see Performance below.

## Performance: batched credit-row prefetch

A first real `build-record-routes` run against `snapshot=20260601` (140
matched albums, full one-hop corpus) did not finish in 49 minutes and was
killed. Instrumented timing (measured locally, same host/dataset) isolated
the cause: `rounds_generator.py`'s candidate-discovery loops called
`rounds.build_round_from_path` → `build_round_hop` → `CreditGraph.credit_rows`
once per candidate hop — a single-row query against the live `credits` view
(unindexed `read_parquet` scan, unlike the materialized/indexed
`credit_edges` table `neighbors_batch` already uses). Measured cost: opening
the graph took ~214s; `_one_hop_candidates` alone (~106 candidates, one query
per candidate) took 95.8s, roughly 0.5-1s per `credit_rows` call. Two-hop
discovery evaluates on the order of 9,700 backbone pairs × up to 8 bridge
attempts × 2 hops each — tens of thousands of such queries at that per-query
cost, which is what made the run not finish.

Fix: `CreditGraph.credit_rows_for_release_batch` (new, mirrors the existing
`credit_rows_for_releases` batching pattern already used by
`connection_rounds.py`, but preserves `credit_rows`'s exact WHERE-filter
semantics rather than `credit_rows_for_releases`'s narrower one).
`rounds_generator.generate_round_pool` now computes the full candidate
release-id universe from the already-fetched `neighbors_batch` result (no DB
access) and prefetches every candidate hop's credit rows in one query before
discovery runs; `build_round_hop`/`build_round_from_path` accept an optional
pre-fetched map and filter it per hop instead of issuing a fresh query. This
changes only the database-access pattern, not the discovery algorithm's
inputs or outputs — candidate pairing, scoring, and selection are untouched,
and the existing determinism/regeneration tests confirm identical results.

Real-corpus timing after the fix (measured locally, same host/dataset,
140 matched albums): graph open ~222s (unchanged — not this fix's target),
`generate_round_pool` (one-hop discovery + two-hop discovery + scoring +
diversified selection, combined) **29.3s**, down from not finishing within
49 minutes. Real yield: 106 one-hop candidates found (106 selected, below
the 150 target — the real achieved count, not padded), 1,388 two-hop
candidates found (100 selected, target met).

## Validation

`make check` (new `record_routes` contract + generator tests); a real
`build-record-routes` run against `snapshot=20260601`; `validate-record-routes`
on the result; frontend Playwright coverage for `/play/routes/` once built.

## Revisit trigger

If Record Routes ever needs a frozen daily schedule of its own, that is a new,
explicitly separate manifest (never the Connection Guesser's
`connection_daily_manifest.py`) — following the same schema-v1
single-artifact-version rule ADR 0043's slice-5.1 addendum established.

## Addendum: contract hardening and `artifact_version` redefinition (2026-07-23, slice-9 corrective review)

A post-launch corrective review (the same kind of focused audit ADR 0043's
addenda document for the Connection Guesser) found the Record Routes
contract validator (`networked_players_contracts.record_routes`) had fallen
behind the legacy `rounds.py` contract it was built from, and that
`artifact_version` did not cover everything it claimed to. The specific
concern that prompted the review — that the *committed* artifact was itself
missing `mode: "record_routes"` — was directly reproduced against the real
files and **did not confirm** (both files carried the field, and
`validate-record-routes` returned `{"ok": true}`); the gaps below are real
regardless and are what this addendum fixes.

**Reference-integrity checks restored.** `record_routes_failures` never
checked that a hop's `release_id`/`artist_a_id`/`artist_b_id` resolved
against the artifact's own `rounds.releases[]`/`rounds.artists[]`, unlike
`rounds.py`'s equivalent check for the legacy contract. Fixed: added, reusing
the same resolution-set pattern.

**Album validation restored.** `universe.albums[]` had no per-item exact-
key-set check and no duplicate-id detection (`rounds.py`'s `_ALBUM_KEYS`
equivalent). Fixed with a Record-Routes-specific `_ROUTE_ALBUM_KEYS` (7
keys, no `cover_image` — the legacy set doesn't apply since these albums are
art-free by contract, ADR 0045).

**Two-hop bridge continuity now checked, not just generation-time-only.**
Added `_bridge_failures`: a one-hop route's single hop must connect exactly
its two named endpoints; a two-hop route must have exactly one non-endpoint
artist shared between its two hops. Unlike the Connection Guesser's real
middle-uniqueness-across-the-whole-catalog guarantee (which genuinely can't
be re-derived from a published artifact, ADR 0043), this costs nothing to
re-check post-hoc, so there was no reason to leave it generation-time-only.

**`artifact_version` redefined — real semantic change, not a bug fix.**
`record_routes_artifact_version` previously hashed `rounds.rounds[]` alone
and its docstring claimed this "mirrors the Connection Guesser
`artifact_version`." That claim didn't hold: the Guesser embeds every
player-visible/evidentiary field *inside* each round object, so hashing
`rounds[]` alone genuinely covers everything published. Record Routes
normalizes evidence into separate `rounds.releases[]`/`rounds.artists[]`
arrays and album refs into `universe.albums[]`, referenced by id — a route's
own `rounds[]` entry only carries `hops[].role_a/role_b` inline. A silent
edit to a displayed artist's name or an album's title would not have moved
`artifact_version`, even though it changes what a player sees.

Redefined to hash the combined `{albums, rounds, releases, artists}`
payload (excluding only the version fields themselves, to avoid
self-reference). `pool_version` (membership-only, sorted route ids) is
unaffected. Both `packages/graph-core/.../record_routes.py::record_routes_artifact_version`
and its dependency-free mirror in `packages/contracts` were updated together
(same rule as always: if the two disagree, it's a bug in whichever is
stricter by mistake) and a new test
(`test_evidence_only_change_moves_artifact_version`) proves an artist-name
or release-title-only edit now moves the version.

**Route-id orientation is intentionally sensitive, now documented.**
`stable_route_id` sorts `from_album_id`/`to_album_id` before hashing, but
does not canonicalize hop *order* — the same conceptual two-hop path
traversed in the reverse direction (hops reversed) hashes to a different id.
Confirmed by direct construction this was previously undocumented, not
previously broken: `_two_hop_candidates`' `i < c` backbone-index iteration
and artist-id-sorted `from`/`to` assignment mean the generator only ever
discovers each unordered artist pair once, in one orientation, per run.
Decision: **orientation-sensitive by design**, not a defect to fix —
`from_artist_id`/`to_artist_id` are tied to which album renders as sleeve A
vs. sleeve B, a real displayed distinction. Documented in
`stable_route_id`'s docstring and pinned by
`test_reversed_orientation_is_a_different_id_by_design`.

**Real artifact regenerated and republished**, since the `artifact_version`
redefinition changed what the committed file's own version field must equal.
Proven semantically identical to the prior publish before republishing: same
290 routes, same ids, same order, every semantic field (`kind`, `difficulty`,
endpoints, hops, distractors) byte-identical, same `universe.albums`, same
`rounds.releases`/`rounds.artists`, same `counts`; `pool_version` unchanged
(membership didn't move); only `provenance.artifact_version` changed, exactly
as the redefinition intends. Re-validated clean and privacy-scanned before
publishing.

**Frontend hardened to match.** `apps/web/src/game/routes.ts` previously did
a raw `fetch` → `as T` type-cast with no runtime validation — no mode check,
no version-agreement check, no reference-integrity check before dereference,
and a silent `` `Artist ${id}` `` fallback on any lookup miss. New
`apps/web/src/game/routesResolver.ts` (`validateRoutesPool`,
`resolveSelectedRoute`) mirrors `dailyManifest.ts`'s hardened resolver
pattern: every fetched value is untrusted, every failure mode is a typed,
spoiler-free integrity state, never a thrown exception, never a substituted
route. The one-hop reveal's copy was also corrected — it previously named
only one endpoint artist as if they alone "connect" both records; it now
names both endpoint artists and the shared release, matching what a one-hop
route's evidence actually proves. Both chip trays (length, connecting-artist)
now implement the same `role="radio"`/`aria-checked`/roving-tabindex/arrow-
key model already used by the Connection Guesser's chip tray, rather than a
bare `role="radiogroup"` container with plain, non-radio buttons inside it.
