// Types for the Record Routes artifact pair
// (apps/web/public/data/routes/{universe,rounds}.v1.json,
// data/contracts/record-routes-v1.md, ADR 0046).
//
// A genuinely different question from the Connection Guesser: given two real
// albums, how many documented-credit hops connect them (one or two), and who
// is the connecting artist at each hop? This is the album->artist->album
// PATH semantic, never the Guesser's "performer credited on both displayed
// albums" INTERSECTION semantic (game/types.ts) -- do not conflate the two
// contracts or their artifacts.

export const RECORD_ROUTES_MODE = "record_routes";

export interface RoutesProvenance {
  source: string;
  license: string;
  snapshot_date: string;
  generated_by: string;
  graph_core_version: string;
  note: string;
  catalog_version: string;
  /** Complete-content hash of the published rounds array, in order. */
  artifact_version: string;
}

export interface RouteAlbum {
  id: string;
  master_id: number | null;
  main_release_id: number;
  title: string;
  artist_id: number;
  artist: string;
  /** Null when no reliably known original year. */
  year: number | null;
  // Deliberately art-free (ADR 0045/0046): no cover_image/art field. Cover
  // art is resolved by `id` from the shared album-art registry.
}

export interface RoutesUniverse {
  schema_version: 1;
  mode: typeof RECORD_ROUTES_MODE;
  pool_version: string;
  provenance: RoutesProvenance;
  counts: { one_hop: number; two_hop: number; daily_eligible: number };
  albums: RouteAlbum[];
}

export interface RouteHop {
  release_id: number;
  artist_a_id: number;
  artist_b_id: number;
  role_a: string;
  role_b: string;
  quality_flags: string[];
}

export interface RouteDistractor {
  album_id: string;
  reason: string;
}

export type RouteKind = "one_hop" | "two_hop";
export type RouteDifficulty = "easy" | "medium" | "hard" | "very_hard";

export interface RecordRoute {
  /** Content-derived stable id: route-<10 hex chars>. Never ordinal. */
  id: string;
  kind: RouteKind;
  difficulty: RouteDifficulty;
  from_album_id: string;
  to_album_id: string;
  from_artist_id: number;
  to_artist_id: number;
  hops: RouteHop[];
  distractors: RouteDistractor[];
}

/** A release carrying the credit evidence for one hop -- reuses the same
 * shape `data/evidence.ts::buildHopViews` already consumes for the album
 * demo/detail/cohort surfaces (evidence-release images are outside the
 * fingerprinted round content; see ADR 0046). */
export interface RouteEvidenceRelease {
  release_id: number;
  title: string;
  released: string | null;
  country: string | null;
  source_url: string;
  credits: {
    snapshot_date: string;
    release_id: number;
    track_index: number | null;
    track_path: string | null;
    track_position: string | null;
    track_title: string | null;
    credit_scope:
      "release_artist" | "release_credit" | "track_artist" | "track_credit";
    artist_id: number | null;
    name: string;
    anv: string | null;
    join_text: string | null;
    role_text: string | null;
    credited_tracks_text: string | null;
    is_linked: boolean;
    playable_identity: boolean;
  }[];
  images?: { uri150: string }[];
}

export interface RoutesRounds {
  schema_version: 1;
  mode: typeof RECORD_ROUTES_MODE;
  pool_version: string;
  provenance: RoutesProvenance;
  rounds: RecordRoute[];
  releases: RouteEvidenceRelease[];
  artists: { artist_id: number; name: string }[];
}
