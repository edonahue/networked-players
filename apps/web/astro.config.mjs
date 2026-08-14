import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://networked-players.com",
  output: "static",
  trailingSlash: "always",
  // NP_TEST_OUT_DIR lets a one-off test build write to an isolated
  // directory instead of the real dist/ -- unset in every real build, so
  // the default matches Astro's own ("./dist") exactly. See
  // tests/album-cover-placeholder.spec.ts and src/data/albumArt.ts's
  // matching NP_ALBUM_ART_REGISTRY_PATH seam.
  outDir: process.env.NP_TEST_OUT_DIR || "./dist",
});
