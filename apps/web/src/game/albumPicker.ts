// The shape Connect Two Records' pickers select from -- resolved from the
// public album catalog (ADR 0051). Ranking/filtering itself lives in
// siteSearch.ts (graph-expansion Phase 1, plan §7); this module now only
// carries the shared type.

export interface PickableAlbum {
  id: string;
  title: string;
  artist: string;
  artist_id: number;
  year: number | null;
}
