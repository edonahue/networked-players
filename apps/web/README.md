# Web application

The public Networked Players site, hosted at `networked-players.com`. Astro, static
output, deployed to Cloudflare Workers via `wrangler`.

The site is a playable music-connections game on top of an album-centered browsing
experience (the build plan is `docs/WEB_PRODUCT_PLAN.md`; ADR 0037 records the
game-universe/round-engine decisions). Everything runs client-side against
versioned static artifacts — no backend, no accounts.

## Status

- **Landing** (`/`) — hero into the play hub, album-grid teaser, honest status.
- **Play hub** (`/play/`) — the mode shelf.
- **Connection Guesser** (`/play/connection/`) — the flagship: two records land on
  the counter, pick the contributor credited on both from a chip tray (two
  attempts, a spendable clue ladder, an honest give-up), then the round resolves
  into a liner-note evidence sheet. Two-hop rounds (`?kind=two_hop`) hide a middle
  record: find the bridge credit on each side, then name the record. Rounds play
  in five-round sittings with a needle-drop set summary (● clean / ◐ with help /
  ○ revealed).
- **Connection of the Day** (`/play/daily/`) — one deterministic round per UTC
  date, the same for everyone; local streak; spoiler-free share string (date and
  grooves, never a name); one play per day.
- **Albums** (`/albums/`, `/albums/<album-id>/`) — browse grid and per-album
  connection pages: **find the connection** / **reveal every path**, evidence at
  every hop, minimal contributor cards, and cross-links into play. (Old
  `/play/<album-id>/` URLs redirect here.)
- **Cohorts** (`/cohorts/`, `/cohorts/<cohort-id>/`) — a static manifest-driven index
  and detail pages for reviewed playable cohorts. The committed cohort fixture is
  synthetic and clearly labeled until a real, human-reviewed `playable-cohort-v1`
  artifact is explicitly added to the manifest and static import map.
- **About** (`/about/`) — fuller picture, the evidence-vs-influence stance, data & rights.
- **Legacy demo** (`/demo/`) — 2–3 curated paths rendered from a versioned static
  artifact (`public/data/challenge.v1.json`). Predates the album-centered experience
  above; kept during the transition, linked from the footer archive. Runs fully
  client-side; no backend required for this build.

## The game surface

- **Engine and state** live in `src/game/` — a pure state machine (`engine.ts`),
  seeded PRNG (`prng.ts`), needle-drop scoring (`scoring.ts`), versioned local
  stores (`store.ts`: `np.game.v1` in localStorage, `np.set.v1` per-sitting in
  sessionStorage), deterministic synthetic sleeve art (`sleeves.ts`), and the DOM
  controller (`flagship.ts`). Answers are checked in memory; nothing in the page
  marks the correct chip before a round resolves (asserted by tests).
- **Round data** is derived, never hand-edited: `scripts/build-rounds.mjs`
  generates and validates `public/data/game/universe.v1.json` and
  `public/data/game/rounds.v1.json` (`npm run validate:data`, wired into
  `build`/`check`). Two pools, badged in play: a clearly-stamped **synthetic
  universe** and **real records** derived from the curated demo dataset (ADR
  0012), cover art hotlinked from Discogs' CDN only.
- **URL controls** (used heavily by tests): `?round=<id>` pins a round,
  `?seed=` fixes the shuffle, `?kind=two_hop` deals two-hop, `?date=YYYY-MM-DD`
  pins the daily, `?motion=off` collapses animation (as does
  `prefers-reduced-motion`).
- **JS budget** (observed from `npm run build`, 2026-07-19): one game bundle,
  `dist/_astro/flagship.*.js` at ~19.1 KB raw (~7 KB gzipped along with the two
  sub-100-byte page scripts). No frameworks, no runtime dependencies.
- **Accessibility**: chip tray is a keyboard radiogroup with roving tabindex,
  polite/assertive live regions announce guesses/clues/verdicts, focus moves to
  the verdict on resolve, and both reduced-motion signals disable all
  game-surface animation. Still operator work, per the plan's validation matrix
  (not yet exercised): an axe scan, a manual VoiceOver round, and a 200 % zoom
  pass.

Both artifacts are real Discogs-shaped data, but `challenge.v2.json` (the album grid
and play pages) is currently a **small synthetic placeholder**, not the real catalog —
see `data/contracts/challenge-v2.md` and `packages/graph-core`'s
`build-challenge-from-dump`, which generates the real artifact once run against an
actual one-hop dataset (a pending operator step). `challenge.v1.json` (the `/demo/`
page) is **real Discogs data, a small curated subset** — fetched via the Discogs API
(`packages/catalog` `discogs/demo_challenge.py`, see ADR 0012) against a handful of
real artist connections, never the full private seed or collection. Cover art in both
is hotlinked directly from Discogs' own CDN, never downloaded or rehosted.

## Develop

```bash
npm install
npm run dev          # http://127.0.0.1:4321
npm run build        # static output to ./dist
npm run preview
npm run test:smoke   # Playwright smoke tests
```

## Deploy

Production is connected to this GitHub repository through Cloudflare's Git integration.
A push to `main` builds and deploys the site automatically. The command below is an
explicit emergency/manual path, not the normal release workflow:

```bash
npm run deploy       # astro build && wrangler deploy
```

`wrangler.jsonc` serves `./dist` as static assets with a custom-domain route to
`networked-players.com`. Theme preference uses the `networked-players-theme` localStorage
key (dark default, light/dark toggle).

## Next steps (not built yet)

- Generate the real `challenge.v2.json` from the real one-hop dataset (the tooling
  exists; running it against real data is a pending operator step) and swap in for the
  synthetic placeholder.
- Replace the `/demo/` API-sourced dataset with one derived from CC0 Discogs monthly
  dumps (with provenance, no collection membership) once that pipeline (Milestone 8) is
  built.
- Producer/engineer-bridge and six-degrees play modes (see `docs/PRODUCT.md`). Any
  live-search/API mode is additive and must fail gracefully — the static-first core
  always works on its own.
- Operator accessibility passes from `docs/WEB_PRODUCT_PLAN.md` §13: axe dev scan,
  manual VoiceOver round, 200 % zoom.
