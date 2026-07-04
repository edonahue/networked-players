// Types for the static connections-demo artifact (public/data/challenge.v1.json).
//
// These mirror the real credits schema produced by the Discogs ingestion
// pipeline in packages/catalog (see discogs/parquet.py CREDIT_SCHEMA and
// discogs/releases.py). The artifact is real Discogs data for a small, curated
// subset of releases (see packages/catalog discogs/demo_challenge.py and ADR
// 0012) — not the full private seed, and not yet the CC0 monthly-dump-derived
// dataset that Milestone 8 will eventually produce under this same shape.

/** One credited contribution. Faithful to packages/catalog CREDIT_SCHEMA. */
export interface Credit {
  snapshot_date: string;
  release_id: number;
  track_index: number | null;
  track_path: string | null;
  track_position: string | null;
  track_title: string | null;
  /** release_artist | release_credit | track_artist | track_credit */
  credit_scope:
    "release_artist" | "release_credit" | "track_artist" | "track_credit";
  /** Discogs linked artist id (PAN). null when the contributor is not linked. */
  artist_id: number | null;
  /** Credited name as given in the source. */
  name: string;
  /** Artist Name Variation — display override; kept separate from artist_id. */
  anv: string | null;
  join_text: string | null;
  /** Original, un-normalized role text. */
  role_text: string | null;
  credited_tracks_text: string | null;
  /** true when artist_id resolves to a linked artist. */
  is_linked: boolean;
  /** true only for linked artists that may act as graph nodes. */
  playable_identity: boolean;
}

/** A cover-art image, hotlinked from Discogs' own CDN — never downloaded or rehosted. */
export interface ReleaseImage {
  uri: string;
  uri150: string;
  width: number;
  height: number;
}

/** A release plus its credit rows. */
export interface Release {
  snapshot_date: string;
  release_id: number;
  status: string;
  title: string;
  country: string | null;
  released: string | null;
  master_id: number | null;
  master_is_main_release: boolean | null;
  data_quality: string | null;
  source_url: string;
  images: ReleaseImage[];
  credits: Credit[];
}

/** A playable identity (linked artist only). */
export interface Artist {
  artist_id: number;
  name: string;
}

/** One step of a path: two artists co-credited on the same release. */
export interface Hop {
  release_id: number;
  artist_a_id: number;
  artist_b_id: number;
}

/** A curated, documented path between two artists. */
export interface Path {
  id: string;
  label: string;
  description: string;
  from_artist_id: number;
  to_artist_id: number;
  hops: Hop[];
}

export interface Provenance {
  source: string;
  license: string;
  snapshot_date: string;
  source_url: string;
  generated_by: string;
  catalog_parser_version: string;
  catalog_schema_version: number;
  note: string;
}

export interface Challenge {
  schema_version: number;
  provenance: Provenance;
  releases: Release[];
  artists: Artist[];
  paths: Path[];
}

// --- Challenge v2 (album-centered) -----------------------------------------
// Mirrors packages/graph-core's challenge.py output; see
// data/contracts/challenge-v2.md for the full field-by-field contract.
// Albums are the entry points here; releases are demoted to evidence beneath
// the hops that justify each connection.

/** An album (a matched master or release) — the top-level browsing unit. */
export interface AlbumV2 {
  id: string;
  master_id: number | null;
  main_release_id: number;
  title: string;
  artist_id: number;
  artist: string;
  year: number | null;
  /** Presentational only, hotlinked from Discogs — never load-bearing evidence. */
  cover_image: ReleaseImage | null;
}

/** A release demoted to evidence: same fields as Release, minus images, with
 * credits filtered to only the linked artists that are hop endpoints. */
export interface EvidenceRelease {
  snapshot_date: string;
  release_id: number;
  status: string;
  title: string;
  country: string | null;
  released: string | null;
  master_id: number | null;
  master_is_main_release: boolean | null;
  data_quality: string | null;
  source_url: string;
  credits: Credit[];
}

/** A curated, documented path between two albums' artists. */
export interface PathV2 {
  id: string;
  label: string;
  description: string;
  from_album_id: string;
  to_album_id: string;
  from_artist_id: number;
  to_artist_id: number;
  hops: Hop[];
}

export interface ProvenanceV2 {
  source: string;
  license: string;
  snapshot_date: string;
  generated_by: string;
  graph_core_version: string;
  note: string;
}

export interface ChallengeV2 {
  schema_version: number;
  provenance: ProvenanceV2;
  albums: AlbumV2[];
  artists: Artist[];
  paths: PathV2[];
  releases: EvidenceRelease[];
}
