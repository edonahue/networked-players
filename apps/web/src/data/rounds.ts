// Types for the game-rounds artifact pair (data/contracts/rounds-v1.md).
// Produced by `networked-players-catalog build-rounds-from-dump`. Every hop
// requires an explicit, displayable instrument/vocal role on both sides
// (role_a/role_b) -- a narrower gate than challenge.v2's evidence, which
// only requires *some* documented credit. Reuses Artist/EvidenceRelease from
// challenge.ts: both artifacts share graph-core's release/credit shape.

import type {
  Artist,
  Credit,
  EvidenceRelease,
  ReleaseImage,
} from "./challenge";

export type { Artist, Credit, EvidenceRelease };

/** An album that is a round endpoint or a round's distractor. Same shape as
 * AlbumV2, independently declared since the two artifacts version separately. */
export interface RoundAlbum {
  id: string;
  master_id: number | null;
  main_release_id: number;
  title: string;
  artist_id: number;
  artist: string;
  year: number | null;
  cover_image: ReleaseImage | null;
}

export interface RoundHop {
  release_id: number;
  artist_a_id: number;
  artist_b_id: number;
  /** The literal Discogs role_text that satisfied the performer allowlist. */
  role_a: string;
  role_b: string;
  quality_flags: string[];
}

export interface RoundDistractor {
  album_id: string;
  /** Presentational only, e.g. "no_known_path" -- never a factual claim. */
  reason: string;
}

export interface Round {
  id: string;
  kind: "one_hop" | "two_hop";
  difficulty: "easy" | "medium" | "hard" | "very_hard";
  from_album_id: string;
  to_album_id: string;
  from_artist_id: number;
  to_artist_id: number;
  hops: RoundHop[];
  distractors: RoundDistractor[];
}

export interface RoundsProvenance {
  source: string;
  license: string;
  snapshot_date: string;
  generated_by: string;
  graph_core_version: string;
  note: string;
}

export interface UniverseV1 {
  schema_version: number;
  pool_version: string;
  provenance: RoundsProvenance;
  counts: { one_hop: number; two_hop: number; daily_eligible: number };
  albums: RoundAlbum[];
}

export interface RoundsV1 {
  schema_version: number;
  pool_version: string;
  provenance: RoundsProvenance;
  rounds: Round[];
  releases: EvidenceRelease[];
  artists: Artist[];
}

// --- Daily manifest (data/contracts -- frozen, append-only date schedule) ---

export interface DailyManifestEntry {
  date: string;
  round_id: string;
}

export interface DailyManifestV1 {
  schema_version: number;
  pool_version: string;
  generated_at: string;
  schedule: DailyManifestEntry[];
}
