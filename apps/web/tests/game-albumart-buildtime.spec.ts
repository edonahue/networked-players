// Unit coverage for the Astro build-time cover-art resolver
// (src/data/albumArt.ts::coverFor), used by /albums/[album].astro to choose
// between rendering .play-header__cover (a real Discogs hotlink) or
// .play-header__placeholder. This resolver reads the real registry off disk
// via readFileSync at module load (process.cwd() during astro build, same
// as during `npx playwright test` run from apps/web/) -- it is a different
// module from the client-side src/game/albumArt.ts already covered by
// game-albumart.spec.ts, and its module-level singleton can't be swapped
// via page.route the way client-side fetches can (see the smoke-test
// helpers' own comment on this).
//
// No committed album currently lacks art (0 of 140 catalog albums), so no
// real page can be driven into the placeholder branch today -- this tests
// the exact condition that branch depends on (coverFor returning null)
// directly, against the real, already-loaded production registry, rather
// than mocking one.

import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { coverFor } from "../src/data/albumArt";
import { DATA_DIR } from "./helpers/catalogFacts";

test("coverFor resolves real registry art for a real connected album", async () => {
  // Invariant: every album the registry carries resolves to real https
  // Discogs art. The album is the first registry entry (artifact lookup),
  // not a named record.
  const registry = JSON.parse(
    readFileSync(join(DATA_DIR, "catalog/album-art.v1.json"), "utf8"),
  ) as { albums: { album_id: string }[] };
  const cover = coverFor(registry.albums[0].album_id);
  expect(cover).not.toBeNull();
  expect(cover?.uri150).toMatch(/^https:\/\/i\.discogs\.com\//);
  expect(cover?.uri).toMatch(/^https:\/\/i\.discogs\.com\//);
});

test("coverFor returns null for an album absent from the registry -- the exact condition that drives the page's placeholder branch", async () => {
  expect(coverFor("master-does-not-exist")).toBeNull();
});
