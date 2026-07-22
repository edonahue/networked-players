# Web product plan: from evidence viewer to playable connections game

Status: **proposed plan** (nothing below exists until its PR lands). Companion to
`docs/BUILD_PLAN.md` (pipeline/infra track); this document owns the frontend product
expansion. Grounded in a full inspection of `apps/web` at the current HEAD, the data
contracts, ADRs 0002/0012/0026/0027/0031/0035/0036, and an interview with the operator
(decisions recorded in §15).

---

## 1. Executive recommendation

**Build the Connection Guesser** — a mobile-first, quick-round deduction game where two
record sleeves land on the table and the player identifies the documented contributor
who links them — **plus a frozen, manifest-driven Connection of the Day** (ADR 0043;
originally planned as date-seeded, now resolved from a committed schedule), on top of the existing
static Astro architecture, powered by two clearly-badged content pools: a designed
synthetic universe and real rounds derived from the existing curated Discogs demo data.

- **North-star experience:** the crate-digger-detective thrill — squinting at liner-note
  credits, recognizing a name, and being shown the receipts. One round takes 1–3
  minutes; a session is a set of ~5; the daily brings people back.
- **Who it serves:** casual players first (multiple-choice + clue ladder means zero music
  knowledge required to play), with knowledge rewarded through fewer clues and streaks.
- **Why this evolution:** today's `/play/[album]` is spoiler buttons over an evidence
  table — real code, no game loop. The single missing layer (guess → clue → verdict →
  evidence reveal) is exactly what turns the project's existing evidence discipline into
  a product people revisit.
- **Unchanged:** static-first architecture (ADR 0002), zero-framework Astro + vanilla
  TS, the evidence/provenance guardrail tests, the dark record-store design language as
  the base, hotlinked-only cover art (ADR 0012), all data-rights rules.
- **Postponed:** free-text answer entry (expert mode), Hidden Contributor / Behind the
  Boards / Path Builder modes, contributor detail pages beyond a minimal card, `/learn/`,
  sound, any live API.

## 2. Current-state assessment (verified at HEAD)

- **Architecture:** Astro `^7` static output, `trailingSlash: 'always'`, TypeScript,
  zero UI framework, **zero shipped JS bundles** — four inline scripts total (theme init
  + toggle in `src/layouts/BaseLayout.astro`; path picker in `src/pages/demo.astro`;
  reveal engine in `src/components/RevealControls.astro`). Dist ≈ 884 KB, 9 routes,
  single 14.6 KB CSS bundle. 20/20 Playwright tests green.
- **Routes:** `/` (album grid from `challenge.v2.json`), `/about/`, `/demo/` (legacy,
  real data), `/cohorts/` + `/cohorts/[cohortId]/`, `/play/[album]/` (three pages),
  `/404`, `/sitemap.xml` (omits cohort routes).
- **The play gap:** `/play/[album]` has a mode toggle and per-connection Reveal buttons;
  the "guess" is a CSS-redacted title (`.guess-target` in `motif.css`) whose text
  **remains in the DOM and accessible tree** — a screen-reader and game-integrity leak.
  No input, no validation, no distractors, no scoring, no state beyond the theme key.
  On iPhone it renders as redaction bars with buttons.
- **Data inversion:** the flagship surfaces run on a 3-album synthetic placeholder
  (`challenge.v2.json`, no cover art) while the *legacy* `/demo/` holds the real data —
  8 releases, ~1,041 real credit rows, 442 linked artists, real hotlinked
  `i.discogs.com` art (ADR 0012). Gate F (real challenge.v2) is still open.
- **Type fragmentation:** three families in `src/data/` — challenge v1
  (`Path`/`Release`), v2 (`AlbumV2`/`PathV2`/`EvidenceRelease`), cohort
  (`PlayableCohort` with `difficulty`/`hop_count`/`quality_flags`) — and two
  near-duplicate evidence renderers (`PathCard.astro` v1 vs `EvidenceCard.astro` v2).
  Only the cohort contract carries difficulty/strength metadata; only challenge
  contracts carry cover art.
- **Strengths to build on:** the token/motif design system (dark record-store palette,
  groove-placeholder discs, tag taxonomy, timeline hops); `RevealControls`' `data-*`
  delegation; rich stable test hooks; and the guardrail suite
  (`tests/cohort-manifest.spec.ts` forbidden-string + drift checks; smoke test asserting
  connection language never says "worked with"/"influenced").
- **Notable debt:** inline `style=""` on cohort pages; sitemap gaps; no
  `aria-current`/focus management/live regions; no mobile-viewport or a11y test matrix;
  the synthetic `challenge.v2.json` provenance block reads as real CC0 data unless you
  reach `generated_by`.

## 3. Product pillars

1. **Deduce, then see the receipts.** Every round ends by opening the actual evidence —
   roles, scopes, releases — styled as the liner notes it came from. The game is the
   front door; the evidence is the floor.
2. **Participation, never influence.** A credit proves documented participation on a
   recording. No mechanic, copy line, animation, or share string may imply influence,
   friendship, or lineage. (Enforced by existing phrase-scan tests; extended to new
   surfaces.)
3. **Honest about what's real.** Synthetic-universe rounds and real-records rounds are
   visibly badged; synthetic sleeves carry the label in the artwork itself; provenance
   is one tap away and self-identifying in isolation.
4. **Plays great on a phone with no backend.** One-hand portrait play, static artifacts,
   deterministic builds, everything works offline once loaded (ADR 0002; gate H).
5. **Accessible mystery.** Hidden information is hidden from everyone equally and
   revealed to everyone equally — keyboard, screen reader, reduced motion included.
   Nothing "hidden" may sit in the accessible tree.

## 4. Mode portfolio (ranked)

| Mode | Player goal | Interaction | Data needs | Complexity | Verdict |
| --- | --- | --- | --- | --- | --- |
| **Connection Guesser** | Name the contributor linking two records (1-hop); solve bridges then the hidden middle record (2-hop) | Choice chips + clue ladder | Rounds w/ answer set + distractors + clues | High (it's the engine) | **Launch flagship** |
| **Connection of the Day** | Same loop, one frozen daily round + streak + share | Committed manifest, local calendar date (ADR 0043) | Same pool | Low once flagship exists | **Launch** |
| **Hidden Contributor** | Identify the redacted name across 2–3 credit lists | Choice chips over redacted liner notes | Credit excerpts | Medium (new presentation, same engine) | Phase 2 |
| **Behind the Boards** | Guesser restricted to non-performer roles | Flagship variant w/ role filter | Role-category tagging | Low-medium | Phase 2 (note: ADR 0027 excludes non-performer-only credits from *graph hops*; this mode presents them as **evidence spotlights**, not path edges) |
| **Free Explore** | Browse albums/contributors/paths, no score | Album + contributor pages | Existing artifacts | Medium | Phase 2 (grows from `/albums/`) |
| **How Many Hops?** | Guess path length between two records | Single choice | Path lengths | Low | Phase 3 — thin loop alone; good warm-up round type *inside* sets |
| **Missing Record** | Name the hidden middle given the bridges | Inverse of 2-hop stage 2 | Same | Low | Folded into flagship's 2-hop (stage 2 *is* this) |
| **Credit Match** | Match credit rows to sleeves | Tap-to-pair | Credit rows | Medium + drag-alternative burden | Parking lot |
| **Path Builder** | Assemble a valid path from a tray | Ordering | Multi-path data | High | Parking lot |
| **Curated Journey** | Themed sequence (cohorts!) | Guided set | **Reviewed cohort** (none exists yet — ADR 0031) | Medium | Phase 2/3, unblocks when a real cohort is promoted |

## 5. Flagship specification: Connection Guesser

### Round lifecycle (state machine)

```
idle → dealing → guessing ⇄ clue → resolving → revealed → (next | explore | done)
```

- `dealing`: sleeves enter (~700 ms, skippable, reduced-motion = crossfade).
- `guessing`: chips active; clue ladder available; skip available.
- `clue`: one rung revealed, cost applied, back to `guessing`.
- `resolving`: choice locked, verdict computed locally.
- `revealed`: verdict + connection line draw + evidence panel opens; stats written.

The stage element carries `data-phase`; all motion is CSS keyed off it. A `?motion=off`
URL param (and Playwright default) forces instant phase transitions.

### One-hop flow

Two sleeves land left/right (portrait: top/bottom). Prompt: *"One person is credited on
both of these records. Who?"* 4–6 contributor chips below (thumb reach). Chips show
name + role category (e.g. "Bass", "Engineer"). Wrong pick: chip shakes gently, gets
struck through, one more attempt allowed before auto-resolve. Right pick → `revealed`.

### Two-hop flow (bridges, then middle)

Sleeves A and C land; between them a **hidden middle sleeve** — a blank inner-sleeve
silhouette with a groove sheen and "?" catalog stamp (enticing, not a grey box).
- **Beat 1:** "Two different people bridge these records through one hidden album. Pick
  the bridge from each side." Two chip groups (A-side credits, C-side credits).
- **Beat 2:** with both bridges placed, the middle unlocks: "Which record are they both
  on?" 4 album-title chips (with year). Solve → the middle sleeve **flips over** to its
  artwork and the connection line draws A→mid→C.

### Clue ladder (each rung costs one groove of the rating)

1. Middle/answer release year(s). 2. Role category of the answer. 3. Answer's initials.
4. A zoomed liner-note crop: the actual credit row(s) with the name blurred — the
   signature "tiny credits" moment. 5. Eliminate half the wrong chips.

### Answer mechanics

- The engine computes the **full valid answer set** from credits (if two contributors
  connect the endpoints, either is correct); round generation prefers small valid sets.
- Distractors are provably wrong: build-time validation asserts no distractor is
  credited on both endpoints (the single most important correctness test).
- **No answer content in the DOM before reveal.** Chips are data; the verdict/evidence
  markup is rendered only on resolve. (On a static site the round JSON is inspectable —
  this is honest obfuscation for fair play, not security; the daily share string leaks
  nothing.)

### Scoring & local progression ("light & warm")

- Per-round **needle-drop rating**: ● clean solve / ◐ solved with clues / ○ revealed.
- Session set = 5 rounds with an end-of-set sleeve-back summary.
- Daily streak + small local stats (played, solved, clean rate, best streak).
- `localStorage` key `np.game.v1`: `{ version, totals, streak, seenRounds, daily }`,
  written only after `resolving`; versioned with a migration shim; `seenRounds` drives
  repeat avoidance.

### Motion

Deal-in: sleeves translate+rotate from off-canvas like records slid across a counter
(transform/opacity only, ~700 ms, stagger 120 ms). Verdict: connection line draws
hop-by-hop (SVG stroke-dashoffset). Middle flip: 3D rotateY 500 ms. Reduced motion:
crossfades, line appears fully drawn. Everything interruptible; second+ rounds in a
session use the short (250 ms) variant automatically.

### Mobile layout (design target: 390×844 portrait)

Vertical stack: sleeve A / (hidden middle) / sleeve C at ~38vw each; chips in a
bottom-anchored tray; clue button and skip in the tray corners; evidence opens as a
bottom sheet (paper panel) covering ~85vh, swipe/close-button dismissible. Landscape
and ≥760 px: the true left/right playfield with evidence as a right-side drawer.

### Keyboard & screen reader

- Chips: `radiogroup` with roving tabindex, arrows + Enter; every action a real button.
- Polite live region narrates phases ("Two records on the table: X, 1993, and Y, 1998");
  assertive announcement for verdict; focus moves to the verdict heading on reveal.
- Hidden middle: `aria-label="Unknown middle record — solve both bridges to reveal"`.
- Escape skips animation; nothing depends on drag, color, or spatial position alone
  (the prompt always names what's being asked in text).

### Edge cases

Multiple valid answers (accept set); albums without artwork (groove placeholder — synthetic
generator guarantees art, real pool may lack it); hotlink failure (`onerror` →
placeholder disc + title overlay — the sandbox proxy already proved this path matters);
long titles/names (2-line clamp + full text in evidence); exhausted attempts
(auto-reveal, ○ rating, streak preserved on dailies only by solving); repeat visits
(seenRounds filter, reshuffle when pool exhausted); localStorage unavailable (play
works, stats silently off); JS disabled (page renders a no-script explanation + link to
`/albums/` browse experience — play requires JS, browsing does not).

### Test hooks

`data-phase`, `data-round-id`, `data-pool` (synthetic|real), `data-chip`,
`data-chip-state`, `data-clue-rung`, `data-verdict`, `data-testid` on stage regions;
`?seed=` (deterministic PRNG), `?round=` (pin a round id), `?motion=off`.

## 6. Information architecture

```
/                    landing: pitch + "Play today's connection" + play hub + browse teaser
/play/               mode hub (flagship, daily; phase-2 modes appear here)
/play/connection/    flagship Connection Guesser
/play/daily/         Connection of the Day
/albums/             album grid (moves from /)
/albums/[id]/        album detail + its documented connections (evolves /play/[album])
/play/[album]/       kept as redirect stubs → /albums/[id]/ (no broken links)
/cohorts/…           unchanged; links into play when a reviewed cohort lands
/demo/               unchanged, relabeled "Archive: first demo" in nav footer
/about/              unchanged content + a "how the game works / what's synthetic" section
```

Navigation: **Play · Albums · Cohorts · About** (+ theme toggle). Sitemap gains cohort
+ new routes. `aria-current="page"` finally set.

## 7. Visual direction

Territories considered: (a) deep midnight room — unified cinematic dark; (b) liner-note
light — flip to paper-first editorial; (c) **record shop after hours + liner-note
evidence — recommended and chosen.**

- **Stage (play surfaces):** the existing near-black palette, warmed: sleeves rendered
  with subtle lamplight gradient + soft long shadow on a "counter" surface line; chips
  styled as record-shop divider tabs (slightly rotated stamps on hover); handwritten-
  style section eyebrows stay in the existing rust mono caps.
- **Evidence (reveal surfaces):** opens as a **paper panel** — the existing light-theme
  cream tokens used *as a component surface inside dark pages* (`--paper`,
  `--surface-soft`), typeset like liner notes: condensed caps for role labels, tabular
  numerals for years/ids, a stamped catalog line (`REL 90031 · 1977 · MERIDIAN`).
  This gives the game/proof duality a physical metaphor: dark shop, paper insert.
- **Typography roles:** Georgia display for titles/verdicts; Inter for UI; IBM Plex
  Mono for stamps, ids, catalog metadata, clue text. No new fonts.
- **Synthetic artwork:** deterministic SVG sleeve generator keyed by album id — per-label
  design systems (e.g. "Meridian" = geometric duotone; "Copper Kettle" = type-only
  sleeves), each carrying a small in-art `SYNTHETIC` edge stamp that cannot be lost, plus
  a UI provenance badge. Real-pool art is hotlinked `i.discogs.com` per ADR 0012 with
  the placeholder-disc fallback.
- **Real vs synthetic distinction:** pool badge on the stage (`Synthetic universe` /
  `Real records`), in-art stamps for synthetic sleeves, and per-round provenance in the
  evidence panel footer.
- Card geometry: square sleeves, 2 px radius (sleeves are sharp; panels 8–10 px);
  focus states: 2 px `--focus` outset ring; empty/error states use the groove disc +
  one-line mono caption. Loading: sleeve skeleton = static groove placeholder (no
  shimmer).

## 8. Synthetic universe & data model

One internally-consistent fictional scene — working name **"Meridian Tapes"**: a
studio-centered community, ~1974–1996: **~30 albums, ~12 acts, ~22 contributors** (session
players, producers, engineers with recurring careers), 2 fictional labels, deliberate
1-hop and 2-hop structures, ambiguity-tuned distractor kin (two bassists with similar
names), long-title/no-art/many-credit stress cases. All ids in a reserved range
(`syn-` album ids; contributor ids ≥ 90,000,000) so nothing collides with plausible
Discogs ids.

**Provenance rules (from `DATA_AND_RIGHTS.md` + guardrail tests — every field
self-identifies when read alone):** `source: "Synthetic fixture — Meridian Tapes
universe (fictional)"`, license notes fictional, no `seed` key, passes leak scans
(`local/`, `data/private`, `/home/`, `DISCOGS_TOKEN`, `.ssh`) and tone scans ("worked
with"/"collaborated with"/"influenced" forbidden), PAN/ANV separation preserved,
non-linked names never playable, no real cover bytes. This deliberately avoids the
current `challenge.v2.json` trap where provenance reads as real CC0 data.

**Contracts (new, documented in `data/contracts/`):**

`game-universe-v1.json` (authored):
```ts
interface GameUniverse {
  schema_version: 1;
  provenance: SyntheticProvenance;        // self-identifying, see above
  albums: GameAlbum[];                    // { id, title, act, act_id, year, label,
                                          //   art: { kind: "generated" } | { kind: "hotlink", uri150, uri } | null }
  contributors: GameContributor[];        // { id, name, role_categories[] }
  releases: GameRelease[];                // { id, album_id, title, year, catalog_stamp }
  credits: GameCredit[];                  // { release_id, contributor_id, role_text,
                                          //   role_category, credit_scope }   // mirrors CREDIT_SCHEMA vocabulary
}
```

`game-rounds-v1.json` (**derived at build time** by a Node script — deterministic,
validated; the client never derives rounds from raw credits):
```ts
interface GameRound {
  id: string;                              // "syn-1h-014" | "real-1h-003"
  pool: "synthetic-universe" | "real-records";
  kind: "one_hop" | "two_hop";
  difficulty: "easy" | "medium" | "hard";
  endpoints: [AlbumRef, AlbumRef];         // sleeves shown
  middle?: { album: AlbumRef; choices: AlbumRef[] };       // two_hop beat 2
  answer_set: ContributorRef[];            // all valid answers (≥1)
  bridge_answer_sets?: [ContributorRef[], ContributorRef[]];  // two_hop beat 1
  distractors: ContributorRef[];           // provably not valid (validated)
  clues: Clue[];                           // ordered ladder rungs
  evidence: EvidenceRef[];                 // credit rows backing every hop
  provenance_note: string;                 // rendered in evidence footer
}
```

**Round derivation:** *hybrid* — the universe and difficulty/ambiguity structures are
authored; rounds, valid-answer sets, and distractor pools are derived + validated by
the build script (throws on any distractor that satisfies the connection, any empty
answer set, any evidence row that doesn't resolve). The **real pool adapter** derives
one-hop rounds from `challenge.v1.json`'s paths (each 2-hop artist path A→r1→B→r2→C
yields the round "which contributor appears on both r1 and r2?" with sleeves r1/r2 and
answer B) and two-hop rounds where path convergences support them, with distractors
drawn from the 1,041-row credit pool. Migration path: when gate F delivers real
`challenge.v2` data or a reviewed cohort lands (ADR 0031), they plug in as additional
pools under the same `GameRound` shape — cohort `difficulty`/`quality_flags` map
directly onto round difficulty and evidence caveat chips.

## 9. Technical architecture

Vanilla Astro + TypeScript, **no new runtime dependencies, no framework, no animation
library**. The game engine becomes the site's first (small) shipped JS: budget ≤ 25 KB
gzipped total.

```
apps/web/
  src/game/types.ts            GameUniverse/GameRound/engine state types
  src/game/prng.ts             seeded PRNG (mulberry32) — daily = date hash
  src/game/engine.ts           state machine (phases, attempts, clue costs)
  src/game/scoring.ts          needle-drop rating, set summary
  src/game/store.ts            np.game.v1 localStorage + migrations
  src/game/dom.ts              stage renderer: phases → data-attrs, chips, live region
  src/components/game/         SleeveStage, ChipTray, ClueLadder, HiddenMiddle,
                               VerdictPanel, EvidenceSheet, PoolBadge, SetSummary,
                               ShareResult (all .astro shells; behavior via engine)
  src/components/SleeveArt.astro      unified art: hotlink w/ fallback | generated SVG | disc
  src/components/EvidencePanel.astro  consolidated renderer replacing PathCard+EvidenceCard
  src/pages/play/index.astro   hub;  play/connection.astro;  play/daily.astro
  src/pages/albums/…           grid + [id] detail (from current index grid + play/[album])
  scripts/build-rounds.mjs     derive + validate game-rounds-v1.json (build step)
  scripts/gen-sleeves.mjs      deterministic synthetic SVG sleeve generation
  public/data/game/universe.v1.json  ·  rounds.v1.json
  src/styles/game.css          stage/motion/paper-panel styles (tokens extended)
```

Data loading: universe/rounds imported at build for static pages; the engine receives
the round set inlined per page (no client fetch needed; offline-safe). CSS organized as
tokens → global → motif → game. Validation: `npm run validate:data` runs
`build-rounds.mjs --check` + fixture contract checks; wired into `npm run build`.

## 10. Component inventory (key props/states)

- **SleeveArt** `{art, title, sizes}` — states: hotlinked / generated / placeholder /
  error-fallback. Used everywhere a record appears.
- **SleeveStage** `{round}` + `data-phase` — owns deal-in choreography and the counter
  surface; slots A/middle/C.
- **HiddenMiddle** — silhouette sleeve; states: locked / unlockable / flipping / revealed.
- **ChipTray** `{options, kind: contributor|album}` — radiogroup; chip states: idle /
  focused / selected / struck / correct.
- **ClueLadder** `{clues, spent}` — rung states: available / revealed / exhausted; cost
  indicator (groove dots).
- **VerdictPanel** — correct / partial (2-hop beat 1 done) / revealed; focus target;
  hosts "Play another · Explore this contributor · See every credit used".
- **EvidenceSheet / EvidencePanel** — the consolidated paper-panel evidence renderer
  (per-hop credit tables, scope/role/identity chips, provenance footer, caveat chips
  from `quality_flags` when present). Replaces `PathCard` + `EvidenceCard` usage.
- **PoolBadge** `{pool}` — synthetic vs real marker, links provenance.
- **ConnectionLine** — SVG hop path; draw state keyed to phase; static in reduced motion.
- **SetSummary / LocalStats / ShareResult** — end-of-set sleeve-back, stats sheet,
  spoiler-free share string composer.
- **ModeCard** — play-hub entries with availability state (live / coming soon).
- Reused as-is: `BaseLayout`, `SpinningRecord`, `AlbumCard` (grid), cohort components,
  `RevealControls` (browse surfaces only).

## 11. Responsive & accessibility plan

- **Breakpoints:** ≤479 stacked stage + bottom tray/sheet; 480–759 stacked, wider tray;
  760–1099 side-by-side stage, drawer evidence; ≥1100 full playfield with generous
  counter. iPhone landscape: sleeves shrink to ~30vh side-by-side, tray right.
- **Keyboard-only:** every flow completable (chips = arrows+Enter, clue = button, sheet
  = Esc); logical focus order; focus visible always; focus moved intentionally on phase
  changes (verdict heading; sheet close returns to trigger).
- **Screen reader:** phases and verdicts announced (polite/assertive split); hidden
  info excluded from the tree, described by label ("hidden middle record"); evidence
  tables keep `<th scope>` + captions; per-round summary readable as prose.
- **Reduced motion:** all choreography swaps to ≤150 ms fades via one media query +
  the same code path as `?motion=off` (single source of truth).
- **Targets/zoom:** chips ≥ 44 px; layout survives 200 % zoom and large text (rem-based,
  clamps).
- **Testing:** Playwright projects for desktop + iPhone viewport; keyboard-flow specs;
  `prefers-reduced-motion` emulation spec; axe-core scan added as a dev-only check on
  the five key routes (only new dev dependency proposed; runtime stays dependency-free).

## 12. Implementation sequence (8 PRs)

1. **Foundations: universe, rounds, engine, ADR.** Authored `universe.v1.json`,
   `gen-sleeves.mjs`, `build-rounds.mjs` + validation, `src/game/*` engine with
   Playwright-runner unit specs (state machine, scoring, PRNG determinism, distractor
   correctness), contracts docs, **ADR: web game universe & round engine** (records the
   pool strategy, synthetic-provenance rules, and that `challenge.v2.json`'s misleading
   provenance block gets fixed at its generator). No visible UI change. *DoD:* `npm run
   validate:data` + all tests green; fixtures pass leak/tone scans.
2. **IA + design-system extension.** Nav reshape (Play/Albums/Cohorts/About +
   `aria-current`), `/albums/` grid + redirect stubs from `/`-grid and `/play/[album]`,
   `/play/` hub with ModeCards, landing refresh with daily CTA, `game.css` tokens
   (counter, paper panel, divider chips), sitemap completion. *DoD:* smoke tests updated,
   zero broken routes, visual review on both themes.
3. **Flagship one-hop vertical slice** at `/play/connection/`: SleeveStage + ChipTray +
   VerdictPanel + EvidenceSheet, both pools, `?seed`/`?round`/`?motion=off`, keyboard +
   SR pass, mobile sheet. *DoD:* full round playable on iPhone viewport in CI; answers
   absent from DOM pre-reveal (asserted by test).
4. **Two-hop rounds:** HiddenMiddle, bridges-then-middle beats, flip reveal,
   ConnectionLine. *DoD:* 2-hop playable + tested incl. partial-solve states.
5. **Clue ladder + scoring + local state:** ladder UI, needle-drop ratings, set flow,
   `np.game.v1` store + migration test, repeat avoidance, stats sheet. *DoD:*
   persistence/migration specs green; casual-fairness review of clue costs.
6. **Connection of the Day** at `/play/daily/`: frozen manifest selection (ADR 0043,
   superseding the originally-planned date-seeded selection), local-calendar rollover,
   daily state, streak, spoiler-free ShareResult, upcoming/empty/error states. *DoD:*
   same round for a fixed date across builds (test), share string leaks no names (test).
7. **Explore & evidence consolidation:** `/albums/[id]/` upgraded (current play page
   content + connections + "play from here"), minimal contributor cards, EvidencePanel
   replaces PathCard/EvidenceCard everywhere (demo included), cohort pages link into
   play. *DoD:* v1/v2/cohort all render through one evidence component; no dead code.
8. **Polish, a11y/perf audit, docs.** axe pass, reduced-motion audit, JS budget check,
   image fallback audit, `PRODUCT.md` (promote chosen modes from "potential later"),
   `apps/web/README.md`, `BUILD_PLAN.md` cross-link, resolve the "deployed vs not live"
   status-table inconsistency with the operator. *DoD:* validation matrix below fully
   green; subjective play-feel review session done.

Each PR: framework-free (except the single dev-only axe addition in PR 8), tests
included, `npm run build && npx playwright test` green, guardrail scans extended to new
fixtures/pages.

## 13. Validation matrix

- **Automated:** `cd apps/web && npm install && npm run build` (includes
  `validate:data`); `npx playwright test` (unit + browser projects, desktop + iPhone);
  determinism spec (`?seed=42` twice → identical rounds); distractor-correctness build
  check; localStorage migration spec; forbidden-phrase/leak scans over new fixtures.
- **Accessibility:** axe dev scan on `/`, `/play/connection/`, `/play/daily/`,
  `/albums/[id]/`, `/cohorts/[id]/`; manual VoiceOver (iOS) round; keyboard-only round;
  200 % zoom pass.
- **Responsive:** Playwright viewport matrix + manual iPhone portrait/landscape.
- **Subjective:** play 10 rounds per pool on a phone — is the deal-in still delightful
  at round 10? Do clues feel generous or punishing? (Operator judgment, not automatable.)
- **Data/provenance review:** walk `PUBLIC_PRIVATE_BOUNDARY.md`'s pre-publish checklist
  over `universe.v1.json` + `rounds.v1.json` before first commit; confirm synthetic
  stamps render in generated sleeves; confirm real-pool rounds cite ADR 0012 provenance.
- **Offline (gate H rehearsal):** load `/play/daily/`, kill network, complete a round.

## 14. Risks & anti-goals

- **Evidence drowned by spectacle** → paper-panel evidence is a *required* phase of
  every round (revealed state includes it by design, not behind an extra tap on desktop).
- **Motion fatigue** → short-variant after first round per session; skippable; budgeted
  durations in tokens; reduced-motion parity tested.
- **Synthetic-forever drift** → pools are pluggable by contract; ADR records the swap
  plan; provenance badges make synthetic status visible enough to be motivating; real
  pool ships at launch so real data is never "later."
- **Generic trivia feel** → the clue ladder's liner-note crop, divider-tab chips, and
  evidence reveal are the differentiators; no timer, no lives, no points inflation.
- **Client-state creep** → one store module, one versioned key, no framework, engine
  state machine is the only stateful object.
- **Inaccessible mystery** → pillar 5; answers-out-of-DOM is also the a11y fix.
- **Brittle animation tests** → tests assert `data-phase` transitions and end states,
  never pixels or timing curves.
- **Route explosion** → IA capped at §6; contributor pages deliberately minimal cards.
- **Album/release conflation** → UI copy says "record" for sleeves, evidence names the
  release explicitly; types keep `AlbumRef` vs `GameRelease` distinct.
- **Implying influence** → phrase-scan tests extended to game copy, clues, share
  strings; verdict copy templates reviewed in PR 3.
- **Two-hop confusion** (novel mechanic) → beat structure with explicit prompts;
  easy-tier 2-hops use strongly distinct bridges; playtest in PR 4 before polish.

## 15. Decision log

**Resolved by operator interview:** crate-digger-detective character; game-first IA;
quick rounds in ~5-round sets; mobile-first; choice-chips + clue ladder (free-text
deferred); light-and-warm progression (local-only, no accounts); launch = flagship +
daily; two-hop = bridges-then-middle.

**Resolved by this plan (delegated):** record-shop-after-hours + liner-note-paper visual
hybrid; confident-brief motion (~700 ms signature, reduced-motion parity); dual content
pools with badges (synthetic universe + real `challenge.v1`-derived rounds, hotlinked
art per ADR 0012 and operator note); "Meridian Tapes" synthetic universe; derived+
validated rounds artifact; engine as vanilla TS state machine; no new runtime deps;
evidence renderer consolidation; `/albums/` migration with redirect stubs.

**Deliberately open:** free-text expert mode timing; Hidden Contributor/Behind the
Boards sequencing within phase 2; `/learn/` page; sound design (default: none);
contributor-page depth; when gate F's real challenge.v2 and the first reviewed cohort
plug in as pools (operator-gated); whether the daily eventually rotates pools.

## 16. Implementation prompt for PR 1 (ready to paste)

> Implement **PR 1 of `docs/WEB_PRODUCT_PLAN.md` (§12.1): game foundations** in
> `apps/web` on a fresh branch from `main`. Scope: (1) author
> `public/data/game/universe.v1.json` — the "Meridian Tapes" synthetic universe from
> plan §8: ~30 albums, ~12 acts, ~22 contributors with recurring careers across 2
> fictional labels, 1974–1996, including the stress cases (long titles, no-art albums,
> ambiguous same-role contributors); ids in the reserved synthetic ranges; provenance
> self-identifying as fictional in every field per §8. (2) Write
> `scripts/gen-sleeves.mjs` — deterministic SVG sleeve generation keyed by album id
> with per-label design systems and an in-art `SYNTHETIC` edge stamp. (3) Write
> `scripts/build-rounds.mjs` producing `public/data/game/rounds.v1.json` per the
> `GameRound` shape in §8 — one-hop and two-hop rounds from the universe **plus** the
> real-records adapter over `public/data/challenge.v1.json` (each 2-hop artist path
> yields a one-hop round between its two releases; answer = the shared contributor;
> distractors from the release credits). The script must **fail the build** on: any
> distractor credited on both endpoints, any empty answer set, any unresolved evidence
> reference, any leak/tone-scan hit (reuse the forbidden-string lists from
> `tests/cohort-manifest.spec.ts`). (4) Implement `src/game/{types,prng,engine,scoring,
> store}.ts` — the §5 state machine (idle→dealing→guessing⇄clue→resolving→revealed),
> mulberry32 PRNG, needle-drop scoring, and the versioned `np.game.v1` localStorage
> store with a migration shim — **no UI yet**. (5) Add Playwright-runner unit specs
> covering: engine phase transitions incl. two-hop beats and attempt exhaustion;
> scoring; PRNG determinism (`seed 42` twice → identical sequence); store round-trip +
> a v0→v1 migration case; rounds artifact validation (run the build script in-test).
> (6) Add `npm run validate:data` wired into `npm run build`; document both new
> contracts in `data/contracts/` (`game-universe-v1.md`, `game-rounds-v1.md`); add the
> ADR "web game universe and round engine" recording pool strategy, synthetic
> provenance rules, and the plan to fix `challenge.v2.json`'s provenance at its
> generator. Constraints: no new runtime dependencies, no UI framework, no changes to
> existing pages/components (PR 2 owns IA), all existing tests stay green, and do not
> implement anything from plan §12 PRs 2–8. Definition of done: `npm run build` and
> `npx playwright test` green; new fixtures pass the pre-publish checklist in
> `docs/PUBLIC_PRIVATE_BOUNDARY.md`; the round pool contains ≥ 40 synthetic rounds
> (both kinds, three difficulties) and ≥ 6 real-pool rounds.
