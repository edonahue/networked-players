# Agent guidance — apps/web

The public site for `networked-players.com`. See `README.md` in this directory for full
detail; this file is the quick orientation for agents working here.

- **Toolchain: Node/npm, not `uv`.** This app is separate from the Python monorepo. Use
  `npm install`, `npm run dev` (Astro at 127.0.0.1:4321), `npm run build`, `npm run preview`,
  `npm run test:smoke` (Playwright). The root `Makefile`/`uv` commands do not apply here.
- **Static output to Cloudflare Workers** via `wrangler` (`astro.config.mjs` is
  `output: 'static'`, `trailingSlash: 'always'`). Keep it static; deploy is `npm run deploy`.
- **Demo data is synthetic and must stay privacy-safe.** `public/data/challenge.v1.json` is
  invented data with non-real IDs and `example.invalid` URLs. Never add real Discogs release
  IDs, collection membership, API responses, or images. It mirrors the real credits schema in
  `packages/catalog` (`CREDIT_SCHEMA`) so a CC0-derived artifact can replace it later.
- **Static-first:** the demo runs entirely client-side; no live API may become required.
- Preserve evidence-first framing: connections are documented co-credits, never inferred
  influence.
