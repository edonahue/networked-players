// Types for the static connections-demo artifact (public/data/challenge.v1.json).
//
// These mirror the real credits schema produced by the Discogs ingestion
// pipeline in packages/catalog (see discogs/parquet.py CREDIT_SCHEMA and
// discogs/releases.py). The demo data is SYNTHETIC and privacy-safe, but it is
// shaped exactly like real derived catalog facts so a real, CC0-dump-derived
// artifact can be dropped in later without changing this code.

/** One credited contribution. Faithful to packages/catalog CREDIT_SCHEMA. */
export interface Credit {
  snapshot_date: string;
  release_id: number;
  track_index: number | null;
  track_path: string | null;
  track_position: string | null;
  track_title: string | null;
  /** release_artist | release_credit | track_artist | track_credit */
  credit_scope: 'release_artist' | 'release_credit' | 'track_artist' | 'track_credit';
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
