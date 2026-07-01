# Agent guidance — apps/web

The public site for `networked-players.com`. See `README.md` in this directory for full
detail; this file is the quick orientation for agents working here.

- **Toolchain: Node/npm, not `uv`.** This app is separate from the Python monorepo. Use
  `npm install`, `npm run dev` (Astro at 127.0.0.1:4321), `npm run build`, `npm run preview`,
  `npm run test:smoke` (Playwright). The root `Makefile`/`uv` commands do not apply here.
- **Static output to Cloudflare Workers** via `wrangler` (`astro.config.mjs` is
  `output: 'static'`, `trailingSlash: 'always'`). Keep it static; deploy is `npm run deploy`.
- **Demo data is real, curated, and privacy-safe.** `public/data/challenge.v1.json` is real
  Discogs data for a small, curated subset of releases (see `packages/catalog`
  `discogs/demo_challenge.py` and ADR 0012) — not the full private seed. Cover art is hotlinked
  directly from Discogs' own CDN (`i.discogs.com`) in `<img src>`; the repo never downloads,
  stores, or rehosts image bytes. The raw per-release API cache and the private seed itself
  never leave `data/private/` on the coordination host and are never published here. It mirrors
  the real credits schema in `packages/catalog` (`CREDIT_SCHEMA`) so a future CC0-dump-derived
  artifact (Milestone 8) can replace this API-sourced one under the same shape.
- **Static-first:** the demo runs entirely client-side; no live API may become required.
- Preserve evidence-first framing: connections are documented co-credits, never inferred
  influence.
