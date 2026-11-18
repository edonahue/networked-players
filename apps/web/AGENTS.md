# Agent guidance — apps/web

The public site for `networked-players.com`. See `README.md` in this directory for full
detail; this file is the quick orientation for agents working here.

- **Toolchain: Node/npm, not `uv`.** This app is separate from the Python monorepo. Use
  `npm install`, `npm run dev` (Astro at 127.0.0.1:4321), `npm run build`, `npm run preview`,
  `npm run test:smoke` (Playwright). The root `Makefile`/`uv` commands do not apply here.
- **Static output to Cloudflare Workers** via `wrangler` (`astro.config.mjs` is
  `output: 'static'`, `trailingSlash: 'always'`). Keep it static; deploy is `npm run deploy`.
- **Cover art** is hotlinked directly from Discogs' own CDN (`i.discogs.com`) in `<img src>`;
  the repo never downloads, stores, or rehosts image bytes. The raw per-release API cache and
  the private seed itself never leave `data/private/` on the coordination host. The old
  API-sourced `/demo/` and `challenge.v1.json` were retired (Campaign Atlas P5).
- **Fonts** (Inter, IBM Plex Mono) are self-hosted latin woff2 under `public/fonts/` with OFL
  texts; Georgia stays the system display face. No font npm dependency. Share-image fonts
  (satori needs ttf/otf/woff, not woff2) live under `src/og/fonts/` and are never shipped.
- **Share images**: `/og/albums/<id>.png` are generated at build time (satori + resvg) from
  text and vector shapes only; never add album art or any remote fetch to the generator.
- **Static-first:** no live API may become required.
- Preserve evidence-first framing: connections are documented musical performances (ADR 0068,
  performer-only public graph); credits are the evidence. Never inferred influence, and never a
  non-performance credit presented as a connection on its own.
