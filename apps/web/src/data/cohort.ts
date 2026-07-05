// Types for a playable-cohort-v1 artifact (data/contracts/playable-cohort-v1.md).
// Produced by `networked-players-catalog promote-playable-cohort` after an
// explicit, human-reviewed selection step (see ADR 0031) -- deliberately
// narrower than challenge.v2: no cover art, no per-credit evidence rows,
// only the minimum needed to present a reviewed connection.

/** A promoted album -- no cover_image, unlike AlbumV2: the contract omits it. */
export interface CohortAlbum {
  id: string;
  artist_id: number;
  artist: string;
  title: string;
  year: number | null;
}

/** One step of a promoted pair's path. quality_flags mirrors
 * album-cohort-connectivity-v1.md's taxonomy but carries no per-credit
 * role_text/credit_scope rows -- there is no full evidence table to render. */
export interface CohortHop {
  release_id: number;
  artist_a_id: number;
  artist_b_id: number;
  quality_flags: string[];
}

/** A promoted, confirmed-"found" connection between two albums. */
export interface CohortPair {
  album_a_id: string;
  album_b_id: string;
  artist_a_id: number;
  artist_b_id: number;
  difficulty: "easy" | "medium" | "hard" | "very_hard";
  hop_count: number;
  hops: CohortHop[];
  warnings: string[];
}

export interface PlayableCohort {
  schema_version: number;
  cohort_id: string;
  attribution_label: string;
  source_url: string;
  generated_from_scorer_version: number;
  reviewed_at: string;
  review_note: string | null;
  albums: CohortAlbum[];
  pairs: CohortPair[];
}
