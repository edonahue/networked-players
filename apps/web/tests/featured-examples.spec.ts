// Homepage "featured example" unit + integration specs: findBehindTheGlassPath
// pure logic, and a real end-to-end check against the committed catalog.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import type {
  Artist,
  ChallengeV2,
  Credit,
  EvidenceRelease,
  PathV2,
} from "../src/data/challenge";
import { findBehindTheGlassPath } from "../src/data/featuredExamples";
import { behindTheGlassEdgeFilter } from "../src/game/roleTaxonomy";
import {
  buildAlbumIndex,
  buildArtistIndex,
  findAlbumRoute,
  type PathfindingGraph,
} from "../src/game/pathfindingGraph";

function credit(
  releaseId: number,
  artistId: number,
  name: string,
  roleText: string | null,
): Credit {
  return {
    snapshot_date: "20260601",
    release_id: releaseId,
    track_index: null,
    track_path: null,
    track_position: null,
    track_title: null,
    credit_scope: "release_artist",
    artist_id: artistId,
    name,
    anv: null,
    join_text: null,
    role_text: roleText,
    credited_tracks_text: null,
    is_linked: true,
    playable_identity: true,
  };
}

function release(
  id: number,
  title: string,
  credits: Credit[],
): EvidenceRelease {
  return {
    snapshot_date: "20260601",
    release_id: id,
    status: "Accepted",
    title,
    country: null,
    released: "1990",
    master_id: null,
    master_is_main_release: null,
    data_quality: null,
    source_url: `https://example.invalid/release/${id}`,
    credits,
  };
}

function path(
  id: string,
  fromAlbumId: string,
  toAlbumId: string,
  hops: { release_id: number; artist_a_id: number; artist_b_id: number }[],
): PathV2 {
  return {
    id,
    label: id,
    description: "",
    from_album_id: fromAlbumId,
    to_album_id: toAlbumId,
    from_artist_id: hops[0].artist_a_id,
    to_artist_id: hops[hops.length - 1].artist_b_id,
    hops,
  };
}

const ARTISTS: Artist[] = [
  { artist_id: 1, name: "Artist One" },
  { artist_id: 2, name: "Bridge Person" },
  { artist_id: 3, name: "Artist Three" },
  { artist_id: 4, name: "Artist Four" },
];

function baseChallenge(overrides: {
  releases: EvidenceRelease[];
  paths: PathV2[];
}): ChallengeV2 {
  return {
    schema_version: 2,
    provenance: {
      source: "test",
      license: "test",
      snapshot_date: "20260601",
      generated_by: "test",
      graph_core_version: "test",
      note: "test",
    },
    albums: [],
    artists: ARTISTS,
    paths: overrides.paths,
    releases: overrides.releases,
  };
}

test("findBehindTheGlassPath finds a path where both endpoints of every hop are producer/engineer", () => {
  const challenge = baseChallenge({
    releases: [
      release(100, "Not Qualifying Release", [
        credit(100, 1, "Artist One", "Vocals"),
        credit(100, 2, "Bridge Person", "Guitar"),
      ]),
      release(200, "Qualifying Release A", [
        credit(200, 1, "Artist One", "Producer"),
        credit(200, 2, "Bridge Person", "Engineer"),
      ]),
      release(201, "Qualifying Release B", [
        credit(201, 2, "Bridge Person", "Mixed By"),
        credit(201, 3, "Artist Three", "Producer"),
      ]),
    ],
    paths: [
      path("path-fail", "album-a", "album-b", [
        { release_id: 100, artist_a_id: 1, artist_b_id: 2 },
      ]),
      path("path-ok", "album-a", "album-c", [
        { release_id: 200, artist_a_id: 1, artist_b_id: 2 },
        { release_id: 201, artist_a_id: 2, artist_b_id: 3 },
      ]),
    ],
  });

  const result = findBehindTheGlassPath(challenge);
  expect(result?.id).toBe("path-ok");
});

test("findBehindTheGlassPath returns undefined when no path qualifies", () => {
  const challenge = baseChallenge({
    releases: [
      release(100, "Performer Only", [
        credit(100, 1, "Artist One", "Vocals"),
        credit(100, 2, "Bridge Person", "Guitar"),
      ]),
    ],
    paths: [
      path("path-fail", "album-a", "album-b", [
        { release_id: 100, artist_a_id: 1, artist_b_id: 2 },
      ]),
    ],
  });

  expect(findBehindTheGlassPath(challenge)).toBeUndefined();
});

test("findBehindTheGlassPath rejects a multi-hop path when only one hop qualifies", () => {
  const challenge = baseChallenge({
    releases: [
      release(200, "Qualifying Hop", [
        credit(200, 1, "Artist One", "Producer"),
        credit(200, 2, "Bridge Person", "Engineer"),
      ]),
      release(300, "Non-Qualifying Hop", [
        credit(300, 2, "Bridge Person", "Vocals"),
        credit(300, 3, "Artist Three", "Guitar"),
      ]),
    ],
    paths: [
      path("path-partial", "album-a", "album-c", [
        { release_id: 200, artist_a_id: 1, artist_b_id: 2 },
        { release_id: 300, artist_a_id: 2, artist_b_id: 3 },
      ]),
    ],
  });

  expect(findBehindTheGlassPath(challenge)).toBeUndefined();
});

test("findBehindTheGlassPath rejects a hop where only one endpoint has an engineering role", () => {
  const challenge = baseChallenge({
    releases: [
      release(200, "Asymmetric Release", [
        credit(200, 1, "Artist One", "Producer"),
        credit(200, 2, "Bridge Person", "Vocals"),
      ]),
    ],
    paths: [
      path("path-asymmetric", "album-a", "album-b", [
        { release_id: 200, artist_a_id: 1, artist_b_id: 2 },
      ]),
    ],
  });

  expect(findBehindTheGlassPath(challenge)).toBeUndefined();
});

test("findBehindTheGlassPath accepts a hop when ANY role combination across multiple credit rows qualifies", () => {
  // Artist One is credited twice on the same release (release_artist with
  // no role, track_artist as Producer) -- only one of those rows needs to
  // pair with Bridge Person's Engineer credit.
  const challenge = baseChallenge({
    releases: [
      release(200, "Multi-Row Release", [
        credit(200, 1, "Artist One", null),
        credit(200, 1, "Artist One", "Producer"),
        credit(200, 2, "Bridge Person", "Engineer"),
      ]),
    ],
    paths: [
      path("path-multi-row", "album-a", "album-b", [
        { release_id: 200, artist_a_id: 1, artist_b_id: 2 },
      ]),
    ],
  });

  expect(findBehindTheGlassPath(challenge)?.id).toBe("path-multi-row");
});

test("findBehindTheGlassPath skips a path whose hop references a release absent from the artifact", () => {
  const challenge = baseChallenge({
    releases: [],
    paths: [
      path("path-missing-release", "album-a", "album-b", [
        { release_id: 999, artist_a_id: 1, artist_b_id: 2 },
      ]),
    ],
  });

  expect(findBehindTheGlassPath(challenge)).toBeUndefined();
});

test("a real check against the committed catalog: the homepage's Behind the Glass example (if any) names two real, distinct albums", async ({
  request,
}) => {
  const challenge: ChallengeV2 = await (
    await request.get("/data/challenge.v2.json")
  ).json();
  const result = findBehindTheGlassPath(challenge);
  if (!result) {
    // A future regeneration with no qualifying path is a valid, honest
    // state (the homepage renders nothing for this section) -- not a
    // failure of this check.
    return;
  }
  const albumsById = new Map(challenge.albums.map((a) => [a.id, a]));
  const from = albumsById.get(result.from_album_id);
  const to = albumsById.get(result.to_album_id);
  expect(from).toBeTruthy();
  expect(to).toBeTruthy();
  expect(from!.id).not.toBe(to!.id);
});

test("regression tripwire: findBehindTheGlassPath's real pick is actually findable by Connect Two Records' own search", () => {
  // findBehindTheGlassPath (this file) qualifies a pair using
  // challenge.v2.json's bundled credits; Connect Two Records itself
  // searches a DIFFERENT derived artifact, pathfinding/graph.v2.json, via
  // findAlbumRoute. Nothing links these two artifacts' generation together
  // -- a future regeneration could drop the one edge that makes this pair
  // searchable in Connect while leaving the challenge-side credit data (and
  // so this featured pick) untouched, and the homepage would then advertise
  // a "real Behind the Glass route" that Connect itself can't find. This
  // is a tripwire for that regeneration, not a redesign of the selection
  // algorithm -- see the codex-review-retroactive-fixes-progress memory for
  // where this finding came from.
  const challengePath = fileURLToPath(
    new URL("../public/data/challenge.v2.json", import.meta.url),
  );
  const challenge: ChallengeV2 = JSON.parse(
    readFileSync(challengePath, "utf8"),
  );
  const pick = findBehindTheGlassPath(challenge);
  if (!pick) {
    // No qualifying pair in the current committed artifact is a valid,
    // honest state (see the test above) -- nothing to cross-check.
    return;
  }

  const graphPath = fileURLToPath(
    new URL("../public/data/pathfinding/graph.v2.json", import.meta.url),
  );
  const graph: PathfindingGraph = JSON.parse(readFileSync(graphPath, "utf8"));
  const artistIndex = buildArtistIndex(graph);
  const albumIndex = buildAlbumIndex(graph);

  const route = findAlbumRoute(
    graph,
    artistIndex,
    albumIndex,
    pick.from_album_id,
    pick.to_album_id,
    4,
    behindTheGlassEdgeFilter,
  );

  expect(route.ok).toBe(true);
});

test("the real homepage: the Behind the Glass example is deterministic, not the old hardcoded copy", async ({
  page,
}) => {
  // Only the dead hardcoded sentence's own distinguishing phrase is banned
  // here, not "Ziggy Stardust" itself -- that album title could legitimately
  // recur as a real, dynamically-computed pick in a future catalog
  // regeneration, and banning it would fail a correct result just because
  // it happens to match old dead prose.
  await page.goto("/");
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toContain("An editorial pick");
});
