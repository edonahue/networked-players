// Narrow TypeScript ports of real role-text token sets, each powering one
// filtered-search toggle on Connect Two Records: Behind the Glass (ADR
// 0053, PRODUCTION/ENGINEERING), Rhythm Section (drums/bass), and Guitar
// Paths (guitar) -- the latter two shipped in a Phase 2 follow-up slice
// once role_mode_candidates.py's real measurement cleared the launch floor
// for them too (170/455 and 109/196 candidate pairs respectively). This is
// deliberately NOT a full RoleCategory port -- each function answers one
// bounded question, mirroring role_mode_candidates.py's Python-side
// predicates exactly: Behind the Glass mirrors role_taxonomy.py's coarse
// PRODUCTION/ENGINEERING categories (eligibility_engineering.py on the
// Python side); Rhythm Section/Guitar Paths mirror eligibility.py's
// fine-grained `_ROLE_CATEGORY_BY_TOKEN` display-category tokens instead,
// since role_taxonomy.py's coarser STRINGS/PERCUSSION_KEYS buckets bundle
// guitar with bass/banjo/violin and drums with keys/organ -- too broad for
// an instrument-specific mode. Keep every token set in lockstep with its
// Python source by inspection -- a real 2026-08-04 gap where this drifted
// (Python's role_taxonomy.py gained "programmed by"/"drum programming"
// without this file being updated, silently changing real Behind-the-Glass
// eligibility Python-side while the shipped client stayed stale) is now
// covered by pinned parity cases in apps/web/tests/game-roletaxonomy.spec.ts,
// mirroring pathfindingGraph.ts's own BFS-parity pattern
// (pathfinding-bfs-parity.spec.ts) -- a manually-pinned golden value, not an
// automated cross-runner harness, so it still requires updating both sides
// by hand, but a forgotten update now fails a real test instead of silently
// shipping.

const PRODUCTION_AND_ENGINEERING_TOKENS = new Set([
  "producer",
  "co-producer",
  "produced by",
  "engineer",
  "mixed by",
  "mastered by",
  "recorded by",
  // Added 2026-08-04 from a real Jamiroquai-corpus role_taxonomy.py coverage
  // run (packages/graph-core role_taxonomy.py's _ENGINEERING_TOKENS) --
  // "conductor" was added to Python's ARRANGEMENT category in the same run
  // but deliberately does NOT belong here, since ARRANGEMENT isn't part of
  // eligibility_engineering.py's PRODUCTION/ENGINEERING gate either.
  "programmed by",
  "drum programming",
]);

// eligibility.py's _ROLE_CATEGORY_BY_TOKEN entries mapping to "drums" or
// "bass" -- "percussion" is a separate display category and deliberately
// excluded, matching role_mode_candidates.py's _RHYTHM_SECTION_TOKENS
// (which selects on the "drums"/"bass" category values, not "percussion").
const RHYTHM_SECTION_TOKENS = new Set([
  "drums",
  "bass",
  "bass guitar",
  "double bass",
  "upright bass",
]);

// eligibility.py's _ROLE_CATEGORY_BY_TOKEN entries mapping to "guitar".
const GUITAR_TOKENS = new Set([
  "guitar",
  "acoustic guitar",
  "electric guitar",
  "lead guitar",
  "rhythm guitar",
  "slide guitar",
  "steel guitar",
  "pedal steel",
]);

// Verbatim port of eligibility.py's `_PERFORMER_ROLE_TOKENS` -- the full
// instrument/vocal token set, not one of the three narrow filter-mode sets
// above. Added for ADR 0059's recommended-route ranking, which needs a
// general "did a real performer bridge this hop" signal distinct from any
// one filter mode's instrument-specific question. Kept in step with the
// Python source by inspection, the same convention this file's header
// already documents, with its own pinned parity cases in
// apps/web/tests/game-roletaxonomy.spec.ts.
const PERFORMER_TOKENS = new Set([
  // Voice
  "vocals",
  "lead vocals",
  "co-lead vocals",
  "backing vocals",
  "background vocals",
  "additional vocals",
  "choir",
  "chorus",
  "voice",
  "rap",
  "spoken word",
  // Fretted / plucked / bowed strings
  "guitar",
  "acoustic guitar",
  "electric guitar",
  "lead guitar",
  "rhythm guitar",
  "slide guitar",
  "steel guitar",
  "pedal steel",
  "bass",
  "bass guitar",
  "double bass",
  "upright bass",
  "banjo",
  "mandolin",
  "ukulele",
  "sitar",
  "violin",
  "viola",
  "cello",
  "fiddle",
  "harp",
  // Percussion / keys
  "drums",
  "percussion",
  "congas",
  "bongos",
  "timpani",
  "tabla",
  "piano",
  "electric piano",
  "organ",
  "hammond organ",
  "keyboards",
  "synthesizer",
  "synth",
  "accordion",
  "harpsichord",
  "celesta",
  "vibraphone",
  "marimba",
  "xylophone",
  // Brass
  "trumpet",
  "trombone",
  "tuba",
  "french horn",
  "cornet",
  "flugelhorn",
  // Woodwind
  "saxophone",
  "alto saxophone",
  "tenor saxophone",
  "baritone saxophone",
  "soprano saxophone",
  "clarinet",
  "flute",
  "piccolo",
  "oboe",
  "bassoon",
  "bagpipes",
  "harmonica",
]);

// A secondary signal, never a reclassification: these three still count as
// PRODUCTION_AND_ENGINEERING_TOKENS above (Behind the Glass is unaffected).
// Mirrors role_taxonomy.py's `_BACKGROUND_ENGINEERING_TOKENS` exactly --
// the narrow "pure post-production technical" subset the owner asked to
// de-prioritize on core/default pages (2026-08-31), keep in lockstep with
// that Python source by inspection, same convention this file's header
// already documents.
const BACKGROUND_ENGINEERING_TOKENS = new Set([
  "mastered by",
  "recorded by",
  "mixed by",
]);

function normalizeComponent(component: string): string {
  return component
    .replace(/\[.*\]/g, "")
    .trim()
    .toLowerCase();
}

function matchesAnyComponent(roleText: string, tokens: Set<string>): boolean {
  if (!roleText) return false;
  return roleText
    .split(",")
    .some((component) => tokens.has(normalizeComponent(component)));
}

// Splits on a comma only when it's NOT inside a `[...]` qualifier -- a
// plain `roleText.split(",")` (what matchesAnyComponent above uses,
// matching role_taxonomy.py's own classify_role convention)
// breaks on a real, committed credit like "Recorded By [Le Mobile, Los
// Angeles]", whose qualifier itself contains a comma: naively splitting
// first yields "Recorded By [Le Mobile" and " Los Angeles]", neither of
// which has a balanced bracket for normalizeComponent's strip to remove,
// so neither normalizes to a known token (a real false negative caught in
// review). Deliberately scoped to isBackgroundEngineeringRole only, not
// the matchesAnyComponent path every other predicate in this file still
// uses, mirroring role_taxonomy.py's own choice not to widen this fix
// into classify_role's much broader blast radius as part of a
// background-engineering-specific change.
const ROLE_COMPONENT_SPLIT = /,\s*(?![^[]*\])/;

/** True when at least one bracket-aware component of `roleText` is in
 * `backgroundTokens`, and every OTHER component is non-substantive -- not
 * classified as PRODUCTION/ENGINEERING (minus the background set itself)
 * or a PERFORMER token. This file deliberately isn't a full RoleCategory
 * port (see the file header), so "non-substantive" here means "doesn't
 * match any substantive category this file already tracks" rather than a
 * dedicated PACKAGING_BUSINESS/UNKNOWN classification -- the same
 * practical effect role_taxonomy.py's `_classify_component` achieves via
 * its fuller taxonomy, since a real packaging/business token (e.g.
 * "Lacquer Cut By") and a genuinely unrecognized one both fall through to
 * "non-substantive" here exactly as they do there. A genuinely
 * substantive companion (Producer, Engineer, any performer role) still
 * disqualifies the whole credit. */
function matchesBackgroundOrNonSubstantive(
  roleText: string,
  backgroundTokens: Set<string>,
): boolean {
  if (!roleText) return false;
  let sawBackground = false;
  for (const component of roleText.split(ROLE_COMPONENT_SPLIT)) {
    const normalized = normalizeComponent(component);
    if (backgroundTokens.has(normalized)) {
      sawBackground = true;
      continue;
    }
    if (
      PERFORMER_TOKENS.has(normalized) ||
      PRODUCTION_AND_ENGINEERING_TOKENS.has(normalized)
    ) {
      return false;
    }
  }
  return sawBackground;
}

/** True when at least one comma-separated component of `roleText`
 * classifies as PRODUCTION or ENGINEERING. Fail-closed: empty/unrecognized
 * text never qualifies, matching eligibility_engineering.py's default. */
export function isEngineeringOrProductionRole(roleText: string): boolean {
  return matchesAnyComponent(roleText, PRODUCTION_AND_ENGINEERING_TOKENS);
}

/** True when at least one comma-separated component of `roleText` is a
 * drums or bass credit. Fail-closed, same default as the other predicates
 * here. */
export function isRhythmSectionRole(roleText: string): boolean {
  return matchesAnyComponent(roleText, RHYTHM_SECTION_TOKENS);
}

/** True when at least one comma-separated component of `roleText` is a
 * guitar credit (any variant -- acoustic, electric, lead, slide, etc). */
export function isGuitarRole(roleText: string): boolean {
  return matchesAnyComponent(roleText, GUITAR_TOKENS);
}

/** True when at least one comma-separated component of `roleText` is a
 * recognized instrument/vocal token -- did a real performer sing or play
 * on this credit, as opposed to producing, engineering, composing, or a
 * packaging/business role. `None`/empty is always false: unlike the
 * edge-eligibility denylist, billing alone is not proof of performance.
 * Mirrors eligibility.py's `is_performer_role`. */
export function isPerformerRole(roleText: string): boolean {
  return matchesAnyComponent(roleText, PERFORMER_TOKENS);
}

/** True when at least one comma-separated component of `roleText` is a
 * background-engineering token (Mastered By / Recorded By / Mixed By) and
 * every OTHER component is non-substantive -- mirrors role_taxonomy.py's
 * `is_background_engineering_role` exactly, including its round-9 fix: a
 * real, non-substantive companion credit like "Lacquer Cut By" alongside
 * "Mastered By" on the same credit string does not negate the background
 * verdict, even though it isn't itself one of the three narrow background
 * tokens. A secondary display/ranking signal, never a change to edge
 * eligibility or to `isEngineeringOrProductionRole`'s own Behind-the-Glass
 * gate. `None`/empty is always false, and a genuinely mixed credit (e.g.
 * "Producer, Mastered By") is also false -- real creative involvement is
 * present too, so it's never treated as background-only. */
export function isBackgroundEngineeringRole(roleText: string): boolean {
  return matchesBackgroundOrNonSubstantive(
    roleText,
    BACKGROUND_ENGINEERING_TOKENS,
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

/** Edge filter for `findPath`: both endpoints must be a drums/bass credit
 * on the bridging release -- a "Rhythm Section" connection end to end. */
export function rhythmSectionEdgeFilter(roleA: string, roleB: string): boolean {
  return isRhythmSectionRole(roleA) && isRhythmSectionRole(roleB);
}

/** Edge filter for `findPath`: both endpoints must be a guitar credit on
 * the bridging release -- a "Guitar Paths" connection end to end. */
export function guitarPathsEdgeFilter(roleA: string, roleB: string): boolean {
  return isGuitarRole(roleA) && isGuitarRole(roleB);
}
