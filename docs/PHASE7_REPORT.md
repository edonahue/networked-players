# Phase 7 report: catalog expansion to 179 albums + the private research workbench

**Status: complete for PRs A–G's originally-scoped work; PR C's curator
`--mode expansion` tooling and PR D's fuller Explore vision are explicitly
deferred, not abandoned (see "Remaining, after this phase").** Every PR
shipped on its own branch, merged once `make check` (and, for `apps/web`
changes, the full local Playwright suite plus CI) was green — the same
continuous discipline Phases 3–6 established. This report is the closing
summary: what shipped, what was measured, what was rejected or deferred,
and what's left.

## What shipped

Reordered from the plan's own PR-sequence letters (§13 of the Phase 7 plan);
PR numbers are chronological, not lane-ordered.

### PR A — Expansion preflight, route-quality correction, decision ADR

| PR | What it is |
|---|---|
| [#143](https://github.com/edonahue/networked-players/pull/143) | Catalog-expansion readiness measured (route-quality diagnostic, anchor-edge correction) — deliberately not acted on yet, so the measurement itself could be reviewed before any catalog mutation. |
| [#144](https://github.com/edonahue/networked-players/pull/144) | Two traversal-policy fixes and two corrected claims in `NEXT_PATH_BRIEF.md`/`OPERATOR_SETUP.md`, ahead of building anything new on top of them. |

### PR B — Public editorial seed + Bucket A/B/C selection

| PR | What it is |
|---|---|
| [#145](https://github.com/edonahue/networked-players/pull/145) | Public editorial seed contract — a working-set expansion path independent of the private-seed collection. |
| [#146](https://github.com/edonahue/networked-players/pull/146) | Bucket A resolved: 13 personal/editorial anchors ([ADR 0065](decisions/0065-phase7-bucket-a-personal-lane-allocation.md) — 13, not the mission brief's original 16). |
| [#147](https://github.com/edonahue/networked-players/pull/147) | `rank-album-candidates` excludes already-published masters. |
| [#148](https://github.com/edonahue/networked-players/pull/148) | Release-format quantity parsing bounded to int32 — a real malformed value from the actual dump would otherwise crash the build. |
| [#149](https://github.com/edonahue/networked-players/pull/149) | Bucket C coverage-gap measurement (decade/genre/style composition). |
| [#150](https://github.com/edonahue/networked-players/pull/150) | Exact marginal-value evaluation for Bucket B, reusing `credit_edges_sql` rather than a second graph-cost model. |
| [#151](https://github.com/edonahue/networked-players/pull/151) | The Phase 7 expansion-review packet assembler — human review evidence, not an auto-executor. |

### PR C — Editorial review + marginal evaluation tooling

| PR | What it is |
|---|---|
| [#152](https://github.com/edonahue/networked-players/pull/152) | Bucket A wired into `build-public-album-catalog`, without `match_albums`'s per-artist dedup (Bucket A is intentionally allowed multiple albums per artist). |
| [#154](https://github.com/edonahue/networked-players/pull/154) | Buckets B/C wired in, each with its own per-lane audit provenance trail. |
| [#155](https://github.com/edonahue/networked-players/pull/155) | `--already-published-catalog` — preserves prior builds when expanding a live catalog rather than reprocessing from scratch. |

*(Curator `--mode expansion` review UI itself — plan §7 — was not built this
phase; see "Remaining.")*

### PR D — Private research workbench

| PR | What it is |
|---|---|
| [#164](https://github.com/edonahue/networked-players/pull/164) | Slice 1: `compare_albums` + `research-compare --mode albums`. |
| [#165](https://github.com/edonahue/networked-players/pull/165) | Slice 2: `compare_artists`. New `CreditGraph.credit_rows_for_artist` primitive. |
| [#166](https://github.com/edonahue/networked-players/pull/166) | Fixed a recurring CI flake: recentering the Network Explorer could reopen a just-closed evidence drawer (unrelated to PR D's own scope, fixed opportunistically). |
| [#167](https://github.com/edonahue/networked-players/pull/167) | Slice 3: `compare_scenes` (a user-authored, labelled artist-id set). |
| [#168](https://github.com/edonahue/networked-players/pull/168) | The workbench server mode — a third mode of `apps/review/`'s local server, running comparisons from a browser instead of the CLI. |
| [#169](https://github.com/edonahue/networked-players/pull/169) | Explore Slice 1: search (album/artist name) + click-through to real credit-row evidence. |

*(The plan's fuller Explore vision — route filters, scope selection, bounded
graph rendering, compare/pin, saved reproducible request files — is a
separate, larger follow-up; see "Remaining.")*

### PR E/F — Catalog and core graph expansion, game pools, frozen-daily migration

| PR | What it is |
|---|---|
| [#153](https://github.com/edonahue/networked-players/pull/153) | Schema-v2 multi-generation Connection Guesser daily manifest. |
| [#156](https://github.com/edonahue/networked-players/pull/156) | `build-challenge-from-dump` no longer crashes on a same-artist candidate pair — skips it instead. |
| [#157](https://github.com/edonahue/networked-players/pull/157) | Concurrent path search made lazy, so `max_paths` early termination actually applies (a real performance fix uncovered while regenerating at the larger scale). |
| [#158](https://github.com/edonahue/networked-players/pull/158) | Generation-suffixed dataset names allowed in x86 fleet replication. |
| [#159](https://github.com/edonahue/networked-players/pull/159) | A round id already used by a kept generation is never rescheduled. |
| [#160](https://github.com/edonahue/networked-players/pull/160) | The browser resolves schema-v2 multi-generation daily manifests. |
| [#161](https://github.com/edonahue/networked-players/pull/161) | **Publish the Phase 7 catalog expansion: 140 → 179 albums, gen-2 daily cutover** ([ADR 0066](decisions/0066-phase7-daily-manifest-schedule-rewrite-exception.md) — the bounded, audited exception to the never-rewrite daily-manifest rule this cutover needed). The publication boundary this whole phase built toward. |

### PR G — Public browsing, performance, copy, closeout

| PR | What it is |
|---|---|
| [#162](https://github.com/edonahue/networked-players/pull/162) | `about.json`/`llms.txt` catalog stats derived from real artifacts, replacing hardcoded/stale numbers. |
| [#163](https://github.com/edonahue/networked-players/pull/163) | Album shelf gains search (title/artist substring) and sort (title/artist/year), with result count and an honest empty state. |
| [#170](https://github.com/edonahue/networked-players/pull/170) | Album shelf shows the **full** catalog, marking the handful of not-yet-connected albums honestly instead of silently hiding them ([ADR 0067](decisions/0067-album-shelf-shows-the-full-catalog.md) — reverses a prior deliberate, tested decision as the catalog outgrew it). |
| [#171](https://github.com/edonahue/networked-players/pull/171) | Album shelf decade filter, plus URL-addressable search/sort/decade state. |
| [#172](https://github.com/edonahue/networked-players/pull/172) | The homepage's last hardcoded example (a fixed "Behind the Glass" album pair) replaced with a deterministically-computed real one, reusing the same predicate Connect Two Records' own mode uses. |
| [#173](https://github.com/edonahue/networked-players/pull/173) | Site re-profiled at 179 albums — method committed publicly ([ADR 0018](decisions/0018-benchmark-results-local-only.md) discipline), real numbers local-only. |

*(A11y/mobile audit beyond what §14 already required, and this report
itself, close out PR G; see "Remaining" for what PR G explicitly leaves
open.)*

## What was measured before being built

- **§3's route-quality diagnostic (PR A)**: reproduced and root-caused
  before any catalog change, per the plan's own §3 — the anchor-edge and
  role-token correction was a measured before/after, not a guess.
- **Bucket B's marginal value (#150)**: exact evaluation reusing
  `credit_edges_sql` rather than inventing a second graph-cost heuristic —
  the same discipline ADR 0029/0059 already established for avoiding
  hub-biased shortcuts elsewhere in this codebase.
- **PR D's every slice**: each comparison type was manually smoke-tested
  against the real, already-built Jamiroquai topic corpus before being
  trusted, not just synthetic fixtures — this is what caught a real
  `None`/`str` sort crash in Slice 1 that the synthetic-fixture suite alone
  missed entirely.
- **#172's homepage example**: an initial quick Python spot-check
  (exact-string role matching) missed the real qualifying path and
  surfaced an unrelated one by coincidence; caught by cross-checking
  against the actual rendered HTML rather than trusting the approximation,
  then fixed by reusing the real production predicate
  (`behindTheGlassEdgeFilter`) directly instead of reimplementing it.
- **#173's re-profile**: two real bugs in the measurement script itself
  were caught by *not trusting a plausible-looking result* — CDP
  `Performance.getMetrics` silently returning no data, and CDP CPU
  throttling being per-target rather than global (which made the first,
  wrong version of the script report near-identical desktop/mobile
  numbers). Both were caught by noticing the numbers didn't move the way
  they should have, not by the script erroring out.
- **The 179-album re-profile itself**: `graph.v2.json`'s growth (13.6 MB →
  17.5 MB raw) was checked against the album-count growth ratio (+27.9%)
  before being called "proportional, not a regression" — arithmetic, not
  a vibe.

## Rejected or descoped approaches

- **A general reversal of `connectedCatalogAlbums()`'s connected-only
  filter** — ADR 0067 scopes the full-catalog fix to the album shelf
  specifically. `/explore/`'s grid stays connected-only (exploring from a
  disconnected node isn't a meaningful entry into that specific
  experience); the homepage and sitemap were already correct for their
  own separate reasons.
- **Reconstructing a historical 140-album build to get a true before/after
  for every re-profile metric** — rejected as dishonest fabrication risk
  for anything without a genuinely recorded prior number. Only the two
  metrics the plan doc itself recorded (`graph.v2.json` size, sitemap URL
  counts) get a real before/after; everything else in #173 is explicitly
  reported as a new baseline, not a comparison.
- **Folding the album shelf's new "N not yet connected" summary into the
  existing live search-status element** — caught mid-implementation: that
  element gets overwritten by the search/sort JS on every page load,
  which would have silently erased the summary the moment JS ran. Fixed
  with a separate, JS-untouched line instead.
- **PR D's caveat-flag comparison** — the public site's caveat signal
  lives in the evidence-release-registry build path, which a private
  research corpus snapshot doesn't carry the same way; needs its own
  investigation, not a guess bolted onto Slice 1.
- **PR D's "distinct documented routes" (plural) for `compare_artists`** —
  `CreditGraph` has no `excludeEdgeKeys`-style mechanism to force a
  second, genuinely distinct route; only the single shortest route is
  reported, honestly.

## Tests run

- **Backend**: `make check` (Ruff lint/format, mypy, pytest, both
  public-artifact-gate validators) — green at every backend-touching PR
  merge; **1,356 backend tests passing** at this report's close.
- **Frontend**: full local Playwright suite (`npx playwright test`, no
  filter) — **503 passed, 3 pre-existing skips** at this report's close;
  CI (`npm run format:check`, `astro check`/build, Workers Build) green on
  every `apps/web`-touching PR.
- **New coverage this phase** (a partial list; every PR above added its
  own): `packages/graph-core/tests/test_graph.py` (`credit_rows_for_artist`,
  `search_releases`/`search_artists`), `packages/research/tests/
  test_compare*.py` (43 tests across the three comparison types plus the
  shared CLI wiring), `packages/catalog/tests/test_review_server_workbench.py`
  (18 tests, real `ThreadingHTTPServer` black-box HTTP tests, both server-
  side security guards fail-then-pass verified), `apps/web/tests/
  album-grid-dedup.spec.ts`/`albums-directory.spec.ts`/
  `featured-examples.spec.ts` (full-catalog shelf, decade filter + URL
  state, deterministic homepage example — 6+14+8 new tests respectively).
- **Fail-then-pass discipline applied throughout**, including two cases
  where the FIRST attempt at a fix or test was itself wrong and caught by
  this discipline before landing: the explorer-recenter flake's initial
  "clear on next mousemove" fix (wrong — a genuine new hover also fires
  `mouseover` before `mousemove`, so that signal can't distinguish real
  from synthetic; fixed with a `setTimeout(0)` macrotask-boundary check
  instead), and the re-profile script's CPU-throttling bug (the throttled
  run showed no real difference from desktop until the per-page CDP
  session bug was found and fixed).
- **A masked-exit-code process mistake, caught and corrected mid-phase**:
  `npm run format:check | tail -N` discards the real exit code of
  everything piped through `tail`, which let a genuine formatting failure
  in a just-edited file look clean locally until CI caught it. Fixed by
  reading the actual warning-list content from every subsequent check
  rather than trusting a piped exit code.

## Not exercised at Phase 7's close (explicitly out of scope or deferred)

- **PR C's curator `--mode expansion` review UI** (plan §7) — the
  selection/ranking/marginal-evaluation tooling underneath it shipped
  (#147, #149, #150, #151), but the browser review surface itself was not
  built. Explicitly low urgency: no new expansion round is currently
  queued, and building UI with no real candidate data to smoke-test
  against would violate this phase's own "measure against real data, not
  synthetic fixtures alone" discipline.
- **PR D's fuller Explore vision** — route filters, scope selection,
  bounded graph rendering, compare/pin, provenance-always-visible framing,
  saved reproducible request files. Slice 1 (search + evidence
  click-through) shipped; the rest is real, substantial UI/architecture
  work, not another `compare.py`-sized slice.
- **The homepage's contributor-page-count anomaly** (#173) — contributor
  sitemap pages decreased by 28 despite 39 more albums. Flagged as a real,
  observed finding; not investigated further this phase.
- **A11y/mobile audit beyond what individual PRs already covered** — each
  `apps/web` PR this phase ran its own mobile-overflow/keyboard/reduced-
  motion checks where relevant (e.g. the album shelf's decade filter), but
  no phase-wide dedicated a11y sweep was run, unlike Phase 5/6's more
  targeted passes.

## Remaining, after this phase

1. **PR C's curator expansion-review UI** — build when a real next
   expansion round is actually queued, so it can be measured against real
   candidate data from day one rather than a synthetic stand-in.
2. **PR D's fuller Explore vision** — a genuinely separate, larger UI
   effort; scope it as its own small-slice sequence when picked up, the
   same way compare_albums preceded compare_artists/compare_scenes rather
   than shipping all three (or all of Explore) at once.
3. **The contributor-page-count anomaly** — worth a look at the *next*
   catalog expansion if the same pattern (page count moving opposite to
   album count) recurs.
4. **`docs/NEXT_PATH_BRIEF.md`'s remaining open candidates** — Compute/
   platform and Publication/data-operations sections were untouched by
   this phase and remain exactly as they were before it started.
