// Generates a SYNTHETIC Collection (collection-v1 shape) for the one spec that
// renders the Collections pages (collection-page.spec.ts). Nothing here is a
// real collection: the title, intro and player names are obviously synthetic,
// and the file is written under the git-ignored tests/fixtures/.generated/.
//
// Only record ids (and one performer id, so a player link and a role line are
// exercised) come from the committed catalog, because Collection pages link to
// real /albums/<id>/ and /contributors/<id>/ pages. Evidence release ids are
// synthetic (9000001...). The build reads the result through the test-only
// NP_COLLECTIONS_DIR seam (src/data/collections.ts), which is refused unless
// NP_TEST_OUT_DIR is also set.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { isPerformerRole } from "../../src/game/roleTaxonomy";

interface Album {
  id: string;
  title: string;
  artist: string;
}

export const SYNTHETIC_COLLECTION_ID = "synthetic-test-collection";
export const SYNTHETIC_TITLE = "Synthetic Test Collection";
export const SYNTHETIC_INTRO =
  "A synthetic collection used only by automated tests. It is not real.";
const GENERATED_DIR = "tests/fixtures/.generated/collections";

export interface CollectionFixture {
  /** Repo-relative (from apps/web/) path for NP_COLLECTIONS_DIR. */
  dir: string;
  recordIds: string[];
  /** A real contributor id, used as a linked bridge player. */
  linkedPlayerId: number;
  /** A synthetic id with no player page. */
  unlinkedPlayerId: number;
  evidenceIds: number[];
}

export function generateCollectionFixture(webRoot: string): CollectionFixture {
  const read = <T>(rel: string) =>
    JSON.parse(readFileSync(join(webRoot, "public/data", rel), "utf8")) as T;
  const albums = read<{ albums: Album[] }>("challenge.v3.json").albums;
  const contributors = read<{ contributors: { artist_id: number }[] }>(
    "contributors/index.v1.json",
  ).contributors;
  const membership = read<{
    albums: {
      album_id: string;
      credits: {
        artist_id: number;
        role_text: string | null;
        credit_scope: string;
      }[];
    }[];
  }>("albums/credit-membership.v1.json").albums;

  // Four records by four distinct primary artists, in catalog order.
  const records: Album[] = [];
  const seen = new Set<string>();
  for (const a of albums) {
    if (seen.has(a.artist)) continue;
    seen.add(a.artist);
    records.push(a);
    if (records.length === 4) break;
  }
  if (records.length < 4) throw new Error("catalog too small for the fixture");
  const ids = records.map((r) => r.id);

  const indexed = new Set(contributors.map((c) => c.artist_id));
  const first = membership.find((m) => m.album_id === ids[0]);
  const linked = first?.credits.find(
    (c) =>
      indexed.has(c.artist_id) &&
      c.credit_scope !== "release_artist" &&
      isPerformerRole(c.role_text ?? ""),
  );
  if (!linked) throw new Error("no indexed performer on the first record");
  const linkedPlayerId = linked.artist_id;
  const unlinkedPlayerId = 9_000_900;
  const evidenceIds = [9_000_001, 9_000_002, 9_000_003];

  const collection = {
    schema_version: 1,
    collection_id: SYNTHETIC_COLLECTION_ID,
    title: SYNTHETIC_TITLE,
    intro: SYNTHETIC_INTRO,
    generated_at: "2026-01-01T00:00:00Z",
    records: ids,
    bridge_players: [
      {
        artist_id: linkedPlayerId,
        name: "Synthetic Player A",
        records: [ids[0], ids[1]],
      },
      {
        artist_id: unlinkedPlayerId,
        name: "Synthetic Player B",
        records: [ids[1], ids[2]],
      },
    ],
    journey: [
      {
        from_record: ids[0],
        to_record: ids[1],
        via: [linkedPlayerId, unlinkedPlayerId],
        via_names: ["Synthetic Player A", "Synthetic Player B"],
        evidence_release_ids: [evidenceIds[0]],
      },
      {
        from_record: ids[1],
        to_record: ids[2],
        via: [unlinkedPlayerId, 9_000_901],
        via_names: ["Synthetic Player B", "Synthetic Player C"],
        evidence_release_ids: [evidenceIds[1]],
      },
      {
        from_record: ids[2],
        to_record: ids[3],
        via: [9_000_901],
        via_names: ["Synthetic Player C"],
        evidence_release_ids: [],
      },
    ],
    playable_cohort: {
      schema_version: 2,
      route_policy: "shortest-first-found-v1",
      pairs: [
        {
          record_a: ids[0],
          record_b: ids[2],
          hop_count: 2,
          via: [linkedPlayerId, unlinkedPlayerId, 9_000_901],
          via_names: [
            "Synthetic Player A",
            "Synthetic Player B",
            "Synthetic Player C",
          ],
          evidence_release_ids: [evidenceIds[0], evidenceIds[2]],
        },
      ],
    },
    provenance: { collection_version: "collection-v1-000000000000" },
  };
  const index = {
    schema_version: 1,
    collections: [
      {
        collection_id: SYNTHETIC_COLLECTION_ID,
        title: SYNTHETIC_TITLE,
        artifact_path: `/data/collections/${SYNTHETIC_COLLECTION_ID}.v1.json`,
        record_count: ids.length,
        collection_version: collection.provenance.collection_version,
      },
    ],
  };
  const dir = join(webRoot, GENERATED_DIR);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "index.v1.json"), JSON.stringify(index, null, 2));
  writeFileSync(
    join(dir, `${SYNTHETIC_COLLECTION_ID}.v1.json`),
    JSON.stringify(collection, null, 2),
  );
  return {
    dir: GENERATED_DIR,
    recordIds: ids,
    linkedPlayerId,
    unlinkedPlayerId,
    evidenceIds,
  };
}
