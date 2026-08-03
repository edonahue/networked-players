// A narrow TypeScript port of role_taxonomy.py's PRODUCTION/ENGINEERING
// token sets (ADR 0047), used only to power the "Behind the Glass" filter
// on Connect Two Records (ADR 0053). This is deliberately NOT a full
// RoleCategory port -- it answers one bounded question ("is this credit a
// producer/engineer contribution") the same way
// eligibility_engineering.py's is_engineering_or_production_role does on
// the Python side, over the same real token strings. Keep the token sets
// in lockstep with role_taxonomy.py's _PRODUCTION_TOKENS/_ENGINEERING_TOKENS
// by inspection until a shared cross-language fixture exists (mirroring
// pathfindingGraph.ts's own noted BFS-parity gap).

const PRODUCTION_AND_ENGINEERING_TOKENS = new Set([
  "producer",
  "co-producer",
  "produced by",
  "engineer",
  "mixed by",
  "mastered by",
  "recorded by",
]);

function normalizeComponent(component: string): string {
  return component
    .replace(/\[.*\]/g, "")
    .trim()
    .toLowerCase();
}

/** True when at least one comma-separated component of `roleText`
 * classifies as PRODUCTION or ENGINEERING. Fail-closed: empty/unrecognized
 * text never qualifies, matching eligibility_engineering.py's default. */
export function isEngineeringOrProductionRole(roleText: string): boolean {
  if (!roleText) return false;
  return roleText
    .split(",")
    .some((component) =>
      PRODUCTION_AND_ENGINEERING_TOKENS.has(normalizeComponent(component)),
    );
}

/** Edge filter for `findPath`: both endpoints' credited roles on the
 * bridging release must be a producer/engineer contribution -- a "Behind
 * the Glass" connection is a chain of producer/engineer credits end to
 * end, not just one qualifying hop among several. */
export function behindTheGlassEdgeFilter(
  roleA: string,
  roleB: string,
): boolean {
  return (
    isEngineeringOrProductionRole(roleA) && isEngineeringOrProductionRole(roleB)
  );
}
