# Phase 7 report: catalog expansion to 179 albums + the private research workbench

**Status: complete, including a 2026-08-30 closeout recovery pass (PRs
#193–195) that finished the one deliberately-deferred piece — the bounded
Explore graph.** PR C's curator `--mode expansion` review UI remains
deferred deliberately, plus two small pieces of PR D's own follow-on scope
(scope-tier-driven graph traversal, automated a11y coverage for the new
graph view) — see "Remaining, after this phase" and "Not exercised,"
below. Every PR shipped on its
own branch, merged once `make check` (and, for `apps/web` changes, the full
local Playwright suite plus CI) was green — the same continuous discipline
Phases 3–6 established. This report is the closing summary: what shipped,
what was measured, what was rejected or deferred, and what's left.

**This report was originally written after PR #173** (PRs #143–173) and is
now rewritten to cover the real final range through PR #195, across three
merge arcs that happened after that first version: PRs #174–178 (the
report's own initial write, plus three more Explore slices — pin, saved
requests, scope selection); PRs #179–187, an unrelated retroactive
Codex-review-fix audit and cleanup pass, not part of this phase's own
scope; and this closeout's own recovery pass, PRs #193–195 (workbench
graph/scope-tier caching, an album-shelf regression fix, and the bounded
Explore graph). All test counts and catalog figures below are freshly
verified against `main` at PR #195, not transcribed from the original
write.

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
| [#175](https://github.com/edonahue/networked-players/pull/175) | Explore Slice: "compare/pin" — pin a search result directly into the compare form. |
| [#177](https://github.com/edonahue/networked-players/pull/177) | Explore Slice: saved, reproducible comparison request files. |
| [#178](https://github.com/edonahue/networked-players/pull/178) | Explore Slice: scope selection (per-artist scope-tier coverage surfaced in the evidence view). |
| [#193](https://github.com/edonahue/networked-players/pull/193) | **Closeout recovery pass.** `WorkbenchGraphCache`/`ScopeTierCache` — `/api/compare` and artist-evidence lookups no longer rebuild the full graph or recompute scope tiers on every single request (two real, still-open Codex findings from #178, confirmed by this closeout's own investigation). Went through two rounds of Codex-review fixes after merge (see "What was measured," below). |
| [#195](https://github.com/edonahue/networked-players/pull/195) | **Closeout recovery pass, PR D's final piece.** The bounded Explore graph + route filters this report's first version deferred — a one-hop ego-network view (`build_graph_view`, mirroring `apps/web`'s `networkExplorer.ts` shape), a new `GET /api/graph` endpoint built on #193's cache, and an inline SVG+table client, no build step, no CDN. |

*(compare/pin, saved-requests, and scope-selection all shipped in #175/
#177/#178 — three merges after this report's first version described them
as future work. The bounded-graph piece is what #195 finished. Only the
curator `--mode expansion` review UI, a genuinely separate feature from
Explore, remains deferred; see "Remaining.")*

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
| [#174](https://github.com/edonahue/networked-players/pull/174) | This report's first version. |
| [#194](https://github.com/edonahue/networked-players/pull/194) | **Closeout recovery pass.** Fixed #163's own real, still-open Codex finding: a filtered-out album-shelf card's `hidden` attribute alone did nothing (a class selector in `motif.css` outranks the bare `[hidden]` UA rule), and sorting only ever set CSS `order`, never real DOM order — both silently ignored by keyboard/screen-reader navigation. Bundled with the remaining `astro check` hint cleanup. |

*(A11y/mobile audit beyond what §14 already required closes out PR G; see
"Remaining" for what it explicitly leaves open.)*

### Closeout recovery pass (2026-08-30) — everything above already covers its own PRs

PRs #193–195, described in their own PR B/D table rows above, are this
phase's real final work: a Phase-7-closeout Plan-Mode investigation found
the original "Status: complete for PRs A–G" line stale by 14 merged PRs,
most of which (#179–192) turned out to be **unrelated** to Phase 7 at all —
a retroactive Codex-review-fix audit and a separate self-directed cleanup
pass, both real and both merged, neither part of this phase's own mission.
Only #193/#194/#195 are genuinely Phase-7-closeout work, and are already
listed under PR B/G/D above rather than duplicated here.

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
- **#193's graph/scope-tier caches**: measured cold-vs-warm directly against
  a real local topic corpus (`local/research/jamiroquai`) before and after
  — real numbers stay local per ADR 0018 (see
  `docs/SITE_REPROFILE_METHOD.md`'s new "Private workbench cache
  measurement" section for the method); both caches cut repeat-request cost
  by two to three orders of magnitude at this corpus's scale, with the
  absolute savings growing, not shrinking, at full-corpus scale where the
  cold cost is `CreditGraph.open`'s own documented ~2.5 minutes rather than
  under two seconds.
- **#193 itself went through two real rounds of post-merge Codex review**,
  not just CI: the first fix (keying cache identity off a topic corpus's
  declared build parameters) was itself insufficient, caught by a *second*
  Codex pass that named the exact case it missed — a canonical full
  snapshot's manifest has no such field at all, and even a topic corpus's
  version string doesn't change on a same-seed rebuild over corrected
  input. The real fix hashes the manifest's own per-file content hashes
  instead — a fix verified fail-then-pass against the insufficient first
  attempt, not just against the original bug.
- **#195's bounded graph**: smoke-tested against the real Jamiroquai
  corpus, not synthetic fixtures alone, before being trusted — real artist
  names, real degrees, real multi-component role text (e.g. "Featuring,
  Written-By [Cosmic Girl]" on a real Dua Lipa collaboration), confirming
  the role-join logic handles real Discogs data shapes the synthetic test
  fixture's simpler role strings wouldn't have exercised on their own.

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
  merge; **1,400 backend tests passing** at this report's close (fresh
  count against `main` at PR #195, not transcribed from the original
  1,356 figure). `main` stood at 1,377 immediately before this closeout's
  own PRs began — the unrelated #174–192 arcs account for most of the
  growth since the original count; PRs #193–195 alone added 23.
- **Frontend**: full local Playwright suite (`npx playwright test`, no
  filter) — **513 passed, 3 pre-existing skips** at this report's close
  (fresh count, up from 503); CI (`npm run format:check`, `astro
  check`/build, Workers Build) green on every `apps/web`-touching PR.
- **New coverage this phase** (a partial list; every PR above added its
  own): `packages/graph-core/tests/test_graph.py` (`credit_rows_for_artist`,
  `search_releases`/`search_artists`), `packages/research/tests/
  test_compare*.py` (43 tests across the three comparison types plus the
  shared CLI wiring), `packages/catalog/tests/test_review_server_workbench.py`
  (43 tests by this report's close, real `ThreadingHTTPServer` black-box
  HTTP tests, both server-side security guards and the closeout's cache/
  graph-view logic all fail-then-pass verified), `packages/research/tests/
  test_graph_view.py` (5 new tests for the bounded graph view, two of them
  confirmed by mutation testing to actually catch a regression, not just
  pass vacuously), `apps/web/tests/album-grid-dedup.spec.ts`/
  `albums-directory.spec.ts`/`featured-examples.spec.ts` (full-catalog
  shelf, decade filter + URL state, deterministic homepage example —
  6+14+8 new tests respectively).
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
- **A real external process gap during the closeout, disclosed rather than
  papered over**: this repo's own standing rule is to check the automated
  Codex bot's review before merging every PR (the direct cause of the
  #179–183 retroactive-fix arc above, when 15 earlier PRs skipped it).
  Partway through PR #193's second review round, the connected account
  hit its Codex usage limit — confirmed directly (`@codex review` returned
  a limit message, not a review) rather than assumed from silence. PR
  #193 itself still received two full review rounds (5 real findings,
  all fixed and fail-then-pass verified) before the limit hit. PRs #194
  and #195 merged on CI-green plus this closeout's own review/testing
  discipline alone, by explicit owner decision once the limit was
  confirmed real — not a silent downgrade of the process, and worth
  re-checking with Codex once quota resets.

## The 39-vs-40 catalog outcome — closed decision

ADR 0065 originally allocated 13 personal + 19 graph-rich + 8 coverage-gap
= 40 new albums. The real, committed outcome is 13 + **18** + 8 = **39**
(140 → 179, not → 180) — Bucket B landed one short of its own 19-slot
target, confirmed directly against
`docs/data/studio-album-catalog-inclusion-audit-v1.json` and independently
documented in `docs/NEXT_PATH_BRIEF.md`'s 2026-08-30 correction. ADR 0065's
own 2026-08-30 addendum records this and makes the closeout's decision
explicit: **179 stands as final.** No 19th graph-rich candidate is
manufactured after the fact, and no filler album is added anywhere to round
the total back up — inventing a pick now, purely to match a number that was
always projected rather than measured, would be exactly the retroactive
number-fitting this project's own sizing-claim discipline exists to
prevent. This is not an open item for a future phase; see ADR 0065's
addendum for the full reasoning.

## The contributor-count anomaly — investigated, root cause unproven

`#173`'s re-profile first surfaced this: the published contributor sitemap
dropped from 549 to 521 pages (−28) despite 39 more albums, and this
report's first version left it as an unflagged, uninvestigated finding.
This closeout looked into it.

**What's confirmed, directly**: a real, untracked local diff
(`local/tmp/diff-contributor-index.json`, gitignored — not a durable
artifact, kept only for this investigation) shows 283 contributor ids
removed and 255 added between the two index builds — large bidirectional
churn, not simple dedup or a straightforward net removal. Zero name
collisions exist between the removed and added sets, ruling out "the same
person got merged under a corrected identity" as the mechanism.

**Leading hypothesis, not proven**: `contributor_index.py`'s own docstring
states the index is built only from `challenge.v2.json`'s curated paths,
not the full graph. PR #157 (this phase) fixed concurrent path search to
actually respect `max_paths` early termination — a real behavior change to
*which* paths get selected, not just how fast selection runs — and the
179-album candidate pool is also substantially wider than at 140 albums.
Either change, or their combination, could plausibly pull in a different
hop-artist set than before, which would show up as exactly this kind of
churn. This has **not** been verified by actually re-running the ingestion
pipeline end-to-end and diffing intermediate path-selection state (real
operator work per `AGENTS.md`, out of scope for a documentation closeout) —
it remains a plausible, evidence-consistent hypothesis, not a demonstrated
root cause. No contributors were restored or added to force the count back
toward 549; that would treat a symptom without knowing the actual cause,
and 521 is not itself evidence of an error — a curated-path-driven index
legitimately changes membership when the curated paths themselves change.

## Not exercised at Phase 7's close (explicitly out of scope or deferred)

- **PR C's curator `--mode expansion` review UI** (plan §7) — the
  selection/ranking/marginal-evaluation tooling underneath it shipped
  (#147, #149, #150, #151), but the browser review surface itself was not
  built. Explicitly low urgency: no new expansion round is currently
  queued, and building UI with no real candidate data to smoke-test
  against would violate this phase's own "measure against real data, not
  synthetic fixtures alone" discipline.
- **Scope-tier-driven traversal selection in the bounded Explore graph**
  (#195) — considered during the closeout, explicitly deferred: wiring
  `measure_scope_tiers`'s output into graph center/traversal choice would
  need either a second corpus generated per click or new corpus
  architecture neither exists today, not a same-slice addition.
- **Frontend automated a11y coverage for the private workbench's new graph
  view** (#195) — `apps/review` has no Playwright harness at all; the new
  SVG/table view's keyboard accessibility (tabindex, roles, aria-labels,
  Enter/Space handling) was reviewed by hand, not covered by an automated
  test, and the PR says so rather than implying coverage that doesn't
  exist.
- **A11y/mobile audit beyond what individual PRs already covered** — each
  `apps/web` PR this phase ran its own mobile-overflow/keyboard/reduced-
  motion checks where relevant (e.g. the album shelf's decade filter), but
  no phase-wide dedicated a11y sweep was run, unlike Phase 5/6's more
  targeted passes.

## Remaining, after this phase

1. **PR C's curator expansion-review UI** — build when a real next
   expansion round is actually queued, so it can be measured against real
   candidate data from day one rather than a synthetic stand-in.
2. **`docs/NEXT_PATH_BRIEF.md`'s remaining open candidates** — Compute/
   platform and Publication/data-operations sections were untouched by
   this phase and remain exactly as they were before it started.
3. **Re-check Codex's automated PR review once its usage quota resets** —
   #194 and #195 merged without it (see "Tests run," above); worth a
   retroactive look if the quota situation resolves.
4. **The contributor-count anomaly's root cause** — worth actually
   re-running ingestion and diffing path-selection state if the *next*
   catalog expansion reproduces the same pattern (page count moving
   opposite to album count); not worth operator time to chase in isolation
   for a documentation-only closeout.
