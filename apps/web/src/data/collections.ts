// Build-time loader for published Collections (ADR 0074, collection-v1).
//
// A Collection is a reviewed, owner-titled view over the published catalog.
// This module reads what `promote-collection` writes under
// public/data/collections/ (index.v1.json + <id>.v1.json). With no such
// directory -- the state of every real build today -- it returns nothing, and
// every consumer (pages, footer, sitemap, llms.txt) renders nothing at all.
//
// Test seam (tests only): NP_COLLECTIONS_DIR points the loader at an
// alternate directory so a Playwright spec can render a SYNTHETIC collection.
// It is honoured ONLY when NP_TEST_OUT_DIR is also set (an isolated build
// output, never the real dist/), and otherwise the build throws. A production
// build (npm run build / CI / deploy) sets neither, so it can only ever read
// public/data/collections/. Same family as NP_ALBUM_ART_REGISTRY_PATH.

import { existsSync, readFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";

export interface CollectionBridgePlayer {
  artist_id: number;
  name: string;
  records: string[];
}

export interface CollectionJourneyHop {
  from_record: string;
  to_record: string;
  via: number[];
  via_names: string[];
  evidence_release_ids: number[];
}

export interface CollectionPair {
  record_a: string;
  record_b: string;
  hop_count: number;
  via: number[];
  via_names: string[];
  evidence_release_ids: number[];
}

export interface Collection {
  schema_version: number;
  collection_id: string;
  title: string;
  intro: string;
  generated_at: string;
  records: string[];
  bridge_players: CollectionBridgePlayer[];
  journey?: CollectionJourneyHop[];
  playable_cohort?: {
    schema_version: number;
    route_policy: string;
    pairs: CollectionPair[];
  };
  attribution?: { label: string; source_url: string };
  provenance: { collection_version: string };
}

interface CollectionIndex {
  collections: { collection_id: string; artifact_path: string }[];
}

/** Resolves the directory to read, enforcing the test-only seam's guard. */
export function collectionsDirectory(
  env: Record<string, string | undefined> = process.env,
): string {
  const override = env.NP_COLLECTIONS_DIR;
  if (!override) return join(process.cwd(), "public/data/collections");
  if (!env.NP_TEST_OUT_DIR) {
    throw new Error(
      "NP_COLLECTIONS_DIR is a test-only seam and requires NP_TEST_OUT_DIR " +
        "(an isolated test build output). Refusing to read an alternate " +
        "collections directory in a real build.",
    );
  }
  return isAbsolute(override) ? override : join(process.cwd(), override);
}

function readJson<T>(path: string): T | null {
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

let cached: Collection[] | undefined;

/** Every published Collection, ordered by id. Empty when none is published. */
export function loadCollections(): Collection[] {
  if (cached) return cached;
  const dir = collectionsDirectory();
  const index = readJson<CollectionIndex>(join(dir, "index.v1.json"));
  const loaded: Collection[] = [];
  for (const entry of index?.collections ?? []) {
    const collection = readJson<Collection>(
      join(dir, `${entry.collection_id}.v1.json`),
    );
    if (!collection) {
      throw new Error(
        `Collection index lists ${entry.collection_id} but its file is missing.`,
      );
    }
    loaded.push(collection);
  }
  cached = loaded.sort((a, b) =>
    a.collection_id.localeCompare(b.collection_id),
  );
  return cached;
}

export function hasCollections(): boolean {
  return loadCollections().length > 0;
}
