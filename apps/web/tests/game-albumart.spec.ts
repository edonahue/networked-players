// Unit specs for game/albumArt.ts -- pure-node tests in the Playwright runner
// (same pattern as game-canonical.spec.ts). Slice 7A: presentation art is
// resolved by canonical album id from a separately versioned registry, and
// every failure mode yields an empty map (→ placeholder), never a throw.

import { expect, test } from "@playwright/test";
import { buildArtMap } from "../src/game/albumArt";

const VALID = {
  schema_version: 1,
  catalog_version: "catalog-v1-20260601-abc",
  art_version: "album-art-v1-20260601-000000000000",
  albums: [
    {
      album_id: "master-1",
      uri150: "https://i.discogs.com/a/150.jpg",
      uri: "https://i.discogs.com/a/full.jpg",
    },
    {
      album_id: "master-2",
      uri150: "https://i.discogs.com/b/150.jpg",
      uri: "https://i.discogs.com/b/full.jpg",
    },
  ],
};

test("buildArtMap resolves valid entries by album id", () => {
  const map = buildArtMap(VALID);
  expect(map.size).toBe(2);
  expect(map.get("master-1")?.uri150).toBe("https://i.discogs.com/a/150.jpg");
});

test("buildArtMap on a malformed registry yields an empty map, never throws", () => {
  expect(buildArtMap(null).size).toBe(0);
  expect(buildArtMap(42).size).toBe(0);
  expect(buildArtMap({}).size).toBe(0);
  expect(buildArtMap({ albums: "not-an-array" }).size).toBe(0);
  expect(buildArtMap({ albums: [null, 7, {}] }).size).toBe(0);
});

test("buildArtMap drops entries with a non-approved host", () => {
  const map = buildArtMap({
    albums: [
      {
        album_id: "master-x",
        uri150: "https://evil.example.com/a/150.jpg",
        uri: "https://evil.example.com/a/full.jpg",
      },
    ],
  });
  expect(map.size).toBe(0);
});

test("buildArtMap drops entries with a non-https url", () => {
  const map = buildArtMap({
    albums: [
      {
        album_id: "master-x",
        uri150: "http://i.discogs.com/a/150.jpg",
        uri: "https://i.discogs.com/a/full.jpg",
      },
    ],
  });
  expect(map.size).toBe(0);
});
