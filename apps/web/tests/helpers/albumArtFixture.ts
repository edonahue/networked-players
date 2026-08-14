// Generates a genuinely synthetic album-art registry, for the one
// Playwright spec (album-cover-placeholder.spec.ts) that needs to drive
// /albums/[album].astro into its TRUE placeholder branch -- both
// coverFor() and album.cover_image falsy at once.
//
// No committed album currently lacks a registry entry (all 140 have one),
// so no real page can reach that branch through the normal build. This
// helper does NOT derive its fixture from the real committed
// album-art.v1.json (repository guidance: "keep fixtures synthetic and
// reproducible," AGENTS.md) -- it constructs a minimal, hand-shaped,
// empty-albums registry from scratch, so coverFor() returns null for
// every id regardless of what production data currently contains or how
// it's later regenerated. The registry (the thing this test actually
// varies) is fully synthetic; only the ALBUM ID it points the isolated
// build at is real, and unavoidably so -- /albums/[album].astro's pages
// are statically generated per real catalog album via getStaticPaths, the
// same reason every other spec in this suite (pickBoundedConnectedAlbum,
// pickConnectedAlbumWithArt) navigates to a real id rather than a
// fabricated one. That real challenge.v2.json read is used only to find a
// real, connected album whose own cover_image field is also already null
// (true for all 140 today) -- never to shape the registry itself.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

interface ChallengeAlbum {
  id: string;
  title: string;
  cover_image: unknown;
}

interface ChallengePath {
  from_album_id: string;
  to_album_id: string;
}

export interface PlaceholderFixture {
  /** A real, connected album id with no cover_image fallback of its own. */
  albumId: string;
  albumTitle: string;
  /** Repo-relative path (from apps/web/), suitable for NP_ALBUM_ART_REGISTRY_PATH. */
  registryPath: string;
}

const GENERATED_DIR = "tests/fixtures/.generated";
const GENERATED_REGISTRY_PATH = `${GENERATED_DIR}/synthetic-empty-album-art-registry.v1.json`;

/**
 * Picks a real, connected album with no `cover_image` fallback of its own
 * (fewest documented paths, ties broken by id -- same convention as
 * pickBoundedConnectedAlbum), and writes a minimal, fully synthetic,
 * empty-albums art registry -- coverFor() returns null for every id
 * against it, independent of whatever the real committed registry
 * contains. Returns enough to both navigate to the album and point
 * NP_ALBUM_ART_REGISTRY_PATH at the generated file.
 */
export function generatePlaceholderFixture(
  webRoot: string,
): PlaceholderFixture {
  const challenge = JSON.parse(
    readFileSync(join(webRoot, "public/data/challenge.v2.json"), "utf8"),
  ) as { albums: ChallengeAlbum[]; paths: ChallengePath[] };

  const pathCount = new Map<string, number>();
  for (const path of challenge.paths) {
    for (const id of [path.from_album_id, path.to_album_id]) {
      pathCount.set(id, (pathCount.get(id) ?? 0) + 1);
    }
  }
  const candidates = challenge.albums
    .filter(
      (album) =>
        (pathCount.get(album.id) ?? 0) >= 2 && album.cover_image == null,
    )
    .sort(
      (a, b) =>
        pathCount.get(a.id)! - pathCount.get(b.id)! || a.id.localeCompare(b.id),
    );
  if (candidates.length === 0) {
    throw new Error(
      "challenge.v2.json must contain a connected album with no cover_image fallback to build the placeholder fixture from",
    );
  }
  const chosen = candidates[0];

  // Fully synthetic: no field here is read from or derived from any real
  // committed artifact. catalog_version is an arbitrary placeholder --
  // with albums: [], loadRegistry()'s version cross-check never has
  // anything to match against anyway, so its exact value can't affect the
  // outcome.
  const syntheticRegistry = {
    schema_version: 1,
    catalog_version: "catalog-v1-synthetic-test",
    art_version: "album-art-v1-synthetic-test",
    generated_at: "2026-01-01T00:00:00+00:00",
    source: "synthetic test fixture (album-cover-placeholder.spec.ts)",
    license: "n/a -- synthetic test data, no real release artwork",
    albums: [] as unknown[],
  };

  const outPath = join(webRoot, GENERATED_REGISTRY_PATH);
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, JSON.stringify(syntheticRegistry, null, 2));

  return {
    albumId: chosen.id,
    albumTitle: chosen.title,
    registryPath: GENERATED_REGISTRY_PATH,
  };
}
