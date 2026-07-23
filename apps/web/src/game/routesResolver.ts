// Runtime validation for the Record Routes artifact pair (ADR 0046),
// mirroring dailyManifest.ts's hardened resolver pattern. Nothing here
// trusts a TypeScript type assertion as runtime proof -- both fetched JSON
// files are untrusted input, so every field routes.ts depends on is checked
// with a runtime guard before use. A malformed fetch, a wrong-mode artifact,
// a version mismatch between the universe/rounds pair, or a route whose
// endpoints/hops/bridge don't actually resolve must all produce a typed,
// spoiler-free integrity failure -- never a thrown exception, never a
// silently-substituted route, and never a rendered "Artist <id>" standing in
// for a real name the resolver failed to verify.
//
// Two stages, deliberately: `validateRoutesPool` checks the whole fetched
// pair is well-formed and internally consistent (cheap, always run);
// `resolveSelectedRoute` re-verifies only the ONE route `pickRoute` actually
// deals (also cheap -- validating every route in a ~300-route pool on every
// page load would not be, and nothing needs it: a route that resolution
// rejects is simply never shown).

import type {
  RecordRoute,
  RouteAlbum,
  RouteHop,
  RoutesProvenance,
  RoutesRounds,
  RoutesUniverse,
} from "./routesTypes";
import { RECORD_ROUTES_MODE } from "./routesTypes";

export const SUPPORTED_ROUTES_SCHEMA_VERSION = 1;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isProvenance(value: unknown): value is RoutesProvenance {
  return (
    isRecord(value) &&
    isNonEmptyString(value.catalog_version) &&
    isNonEmptyString(value.artifact_version)
  );
}

function isRouteAlbum(value: unknown): value is RouteAlbum {
  return (
    isRecord(value) &&
    isNonEmptyString(value.id) &&
    isNonEmptyString(value.title) &&
    typeof value.artist_id === "number" &&
    isNonEmptyString(value.artist)
  );
}

function isRouteHop(value: unknown): value is RouteHop {
  return (
    isRecord(value) &&
    typeof value.release_id === "number" &&
    typeof value.artist_a_id === "number" &&
    typeof value.artist_b_id === "number" &&
    isNonEmptyString(value.role_a) &&
    isNonEmptyString(value.role_b)
  );
}

/** Structurally safe to dereference -- does NOT check that endpoints/hop
 * references actually resolve against the pool's albums/releases/artists;
 * that's `resolveSelectedRoute`'s job, run only for the one route dealt. */
function isWellFormedRoute(value: unknown): value is RecordRoute {
  if (!isRecord(value)) return false;
  if (!isNonEmptyString(value.id)) return false;
  if (value.kind !== "one_hop" && value.kind !== "two_hop") return false;
  if (
    !isNonEmptyString(value.from_album_id) ||
    !isNonEmptyString(value.to_album_id)
  ) {
    return false;
  }
  if (
    typeof value.from_artist_id !== "number" ||
    typeof value.to_artist_id !== "number"
  ) {
    return false;
  }
  if (!Array.isArray(value.hops) || !value.hops.every(isRouteHop)) return false;
  const expectedHops = value.kind === "one_hop" ? 1 : 2;
  return value.hops.length === expectedHops;
}

export type PoolValidation =
  | {
      ok: true;
      universe: RoutesUniverse;
      roundsArtifact: RoutesRounds;
      routes: RecordRoute[];
    }
  | { ok: false; reason: "malformed-pool" }
  | { ok: false; reason: "wrong-mode" }
  | { ok: false; reason: "version-mismatch" }
  | { ok: false; reason: "empty-pool" };

/** Validate the whole fetched universe/rounds pair before picking a route.
 * Never throws on malformed input -- a `null`/primitive member anywhere in
 * `rounds` is simply excluded from the returned `routes` array rather than
 * dereferenced. */
export function validateRoutesPool(
  universe: unknown,
  roundsArtifact: unknown,
): PoolValidation {
  if (
    !isRecord(universe) ||
    universe.schema_version !== SUPPORTED_ROUTES_SCHEMA_VERSION ||
    !isProvenance(universe.provenance) ||
    !isNonEmptyString(universe.pool_version) ||
    !Array.isArray(universe.albums) ||
    !isRecord(roundsArtifact) ||
    roundsArtifact.schema_version !== SUPPORTED_ROUTES_SCHEMA_VERSION ||
    !isProvenance(roundsArtifact.provenance) ||
    !isNonEmptyString(roundsArtifact.pool_version) ||
    !Array.isArray(roundsArtifact.rounds) ||
    !Array.isArray(roundsArtifact.releases) ||
    !Array.isArray(roundsArtifact.artists)
  ) {
    return { ok: false, reason: "malformed-pool" };
  }
  if (
    universe.mode !== RECORD_ROUTES_MODE ||
    roundsArtifact.mode !== RECORD_ROUTES_MODE
  ) {
    return { ok: false, reason: "wrong-mode" };
  }
  if (
    universe.pool_version !== roundsArtifact.pool_version ||
    universe.provenance.catalog_version !==
      roundsArtifact.provenance.catalog_version ||
    universe.provenance.artifact_version !==
      roundsArtifact.provenance.artifact_version
  ) {
    return { ok: false, reason: "version-mismatch" };
  }

  const routes = roundsArtifact.rounds.filter(isWellFormedRoute);
  if (routes.length === 0) {
    return { ok: false, reason: "empty-pool" };
  }
  return {
    ok: true,
    universe: universe as unknown as RoutesUniverse,
    roundsArtifact: roundsArtifact as unknown as RoutesRounds,
    routes,
  };
}

export type RouteValidation =
  | { ok: true }
  | { ok: false; reason: "missing-endpoint-album" }
  | { ok: false; reason: "unresolved-hop-reference" }
  | { ok: false; reason: "ambiguous-bridge" };

/** Re-verify the ONE route `pickRoute` selected actually resolves against
 * this pool -- endpoints exist, every hop's release/artist references
 * exist, and (two-hop only) exactly one non-endpoint artist bridges the two
 * hops. Mirrors the checks `record_routes_failures` already runs
 * server-side (`packages/contracts/.../record_routes.py`); this is the
 * client-side re-proof that a fetched pool a player's browser sees hasn't
 * been corrupted or truncated in transit. */
export function resolveSelectedRoute(
  route: RecordRoute,
  universe: RoutesUniverse,
  roundsArtifact: RoutesRounds,
): RouteValidation {
  const albumIds = new Set(
    universe.albums.filter(isRouteAlbum).map((a) => a.id),
  );
  if (!albumIds.has(route.from_album_id) || !albumIds.has(route.to_album_id)) {
    return { ok: false, reason: "missing-endpoint-album" };
  }

  const releaseIds = new Set(roundsArtifact.releases.map((r) => r.release_id));
  const artistIds = new Set(roundsArtifact.artists.map((a) => a.artist_id));
  for (const hop of route.hops) {
    if (
      !releaseIds.has(hop.release_id) ||
      !artistIds.has(hop.artist_a_id) ||
      !artistIds.has(hop.artist_b_id)
    ) {
      return { ok: false, reason: "unresolved-hop-reference" };
    }
  }

  if (route.kind === "two_hop") {
    const [hop0, hop1] = route.hops;
    const side0 = new Set([hop0.artist_a_id, hop0.artist_b_id]);
    const side1 = new Set([hop1.artist_a_id, hop1.artist_b_id]);
    if (!side0.has(route.from_artist_id) || !side1.has(route.to_artist_id)) {
      return { ok: false, reason: "ambiguous-bridge" };
    }
    const bridgeCandidates = [...side0].filter(
      (id) =>
        side1.has(id) &&
        id !== route.from_artist_id &&
        id !== route.to_artist_id,
    );
    if (bridgeCandidates.length !== 1) {
      return { ok: false, reason: "ambiguous-bridge" };
    }
  } else {
    const pair = new Set([
      route.hops[0].artist_a_id,
      route.hops[0].artist_b_id,
    ]);
    if (!pair.has(route.from_artist_id) || !pair.has(route.to_artist_id)) {
      return { ok: false, reason: "unresolved-hop-reference" };
    }
  }

  return { ok: true };
}
