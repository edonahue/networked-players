# Web application

The public Networked Players site, hosted at `networked-players.com`. Astro, static
output, deployed to Cloudflare Workers via `wrangler`.

This is an early, well-informed placeholder — more than a stub, less than a finished
product. It explains the project honestly and ships a static, client-side **connections
demo**: documented paths between artists with the credit evidence shown at every hop.

## Status

- **Landing** (`/`) — what the project is, how connections work, honest status.
- **About** (`/about/`) — fuller picture, the evidence-vs-influence stance, data & rights.
- **Demo** (`/demo/`) — 2–3 curated paths rendered from a versioned static artifact
  (`public/data/challenge.v1.json`). Runs fully client-side; no backend required.

The demo data is **real Discogs data, a small curated subset** — fetched via the Discogs
API (`packages/catalog` `discogs/demo_challenge.py`, see ADR 0012) against a handful of
real artist connections, never the full private seed or collection. Cover art is
hotlinked directly from Discogs' own CDN, never downloaded or rehosted. It follows the
same credits schema produced by `packages/catalog` (see `discogs/parquet.py`
`CREDIT_SCHEMA`), so a future CC0-dump-derived artifact (Milestone 8) can replace it
later without code changes.

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

- Replace this API-sourced demo dataset with one derived from CC0 Discogs monthly dumps
  (with provenance, no collection membership) once that pipeline (Milestone 8) is built.
- A larger graph and an interactive pick-two-artists mode. Any live-search/API mode is
  additive and must fail gracefully — the static-first core always works on its own.
