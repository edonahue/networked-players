# Web application

The public Networked Players site, hosted at `networked-players.com`. Astro, static
output, deployed to Cloudflare Workers via `wrangler`.

This is an early, well-informed placeholder — more than a stub, less than a finished
product. It explains the project honestly and ships an album-centered browsing
experience plus a static, client-side **connections demo**: documented paths between
artists (or albums) with the credit evidence shown at every hop.

## Status

- **Landing** (`/`) — an album grid (`public/data/challenge.v2.json`), how connections
  work, honest status.
- **Play** (`/play/<album-id>/`) — one static page per album with a documented
  connection. Two modes: **find the connection** (guess the linking artist, then
  reveal) and **reveal every path** (skip straight to the evidence).
- **About** (`/about/`) — fuller picture, the evidence-vs-influence stance, data & rights.
- **Demo** (`/demo/`) — 2–3 curated paths rendered from a versioned static artifact
  (`public/data/challenge.v1.json`). Runs fully client-side; no backend required for this byikd.

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
