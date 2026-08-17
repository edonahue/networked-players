// Shareable URL state for Connect Two Records (ADR 0059 Phase 5 PR 4).
// Connect is the FIRST surface in this codebase to write URL state --
// verified before starting this module: no `pushState`/`replaceState`
// anywhere in `apps/web/src`, only the read-once-at-init
// `new URLSearchParams(window.location.search)` pattern `flagship.ts`/
// `routes.ts` already use for `?round=`/`?seed=`/`?motion=off`. This module
// extends that READ convention and adds the WRITE half, kept here as pure,
// DOM-free logic so it can be unit-tested without a browser -- `connect.ts`
// owns the actual `history.pushState`/`replaceState`/`popstate` calls.
//
// Album **ids**, never display titles: a title can collide, get renamed
// case-differently, or contain characters requiring escaping a reader
// can't verify at a glance; an id is exactly what `albumIndex`/`catalog`
// already key on everywhere else in this codebase.

/** Canonical parameter order -- always serialized in exactly this order
 * regardless of insertion order, so two functionally-identical searches
 * produce byte-identical URLs (shareable, comparable, diffable). */
const PARAM_ORDER = ["a", "b", "mode"] as const;

export interface ConnectUrlState {
  albumAId: string;
  albumBId: string;
  /** The checked role-filter-mode radio value, e.g. "behind-the-glass" --
   * "none" (the unfiltered default) is never actually present in this
   * field's source URL param; see `parseConnectUrlParams`. */
  mode: string;
}

const DEFAULT_MODE = "none";

/** Reads `a`/`b`/`mode` from a URL's query string (either
 * `location.search` or a `popstate` event's `location.search` at fire
 * time -- both are plain strings, so this takes a string, not a `URL`).
 *
 * Returns `null` for anything that doesn't describe a real, distinct
 * pair worth acting on: `a`/`b` missing or empty, or `a === b` (a visitor
 * cannot search a record against itself, and silently keeping one side
 * of a self-referential link while dropping the other would be an
 * arbitrary, unrequested repair rather than a safe rejection). A
 * duplicated param (`?a=x&a=y`) resolves via `URLSearchParams.get`'s own
 * first-occurrence rule -- deterministic, not an error case.
 *
 * `mode` is validated against `validModes` (the caller's own known
 * filter-mode keys, injected rather than duplicated here so this module
 * never needs to track connect.ts's filter vocabulary). An unrecognized
 * or absent `mode` value resolves to `"none"`, never an error -- a
 * visitor who lands on a link naming a role-filter mode a later deploy
 * retired still gets a working unfiltered search instead of a dead page. */
export function parseConnectUrlParams(
  search: string,
  validModes: ReadonlySet<string>,
): ConnectUrlState | null {
  const params = new URLSearchParams(search);
  const albumAId = params.get("a");
  const albumBId = params.get("b");
  if (!albumAId || !albumBId) return null;
  if (albumAId === albumBId) return null;
  const rawMode = params.get("mode");
  const mode = rawMode && validModes.has(rawMode) ? rawMode : DEFAULT_MODE;
  return { albumAId, albumBId, mode };
}

/** Builds the canonical query string for a completed search -- `mode` is
 * omitted entirely when it's the unfiltered default, keeping the common
 * case's URL short and keeping `parseConnectUrlParams`'s "absent means
 * none" contract exact (there is only ever one way to write the default,
 * never a redundant `mode=none` some links have and others don't). */
export function buildConnectSearchParams(
  state: ConnectUrlState,
): URLSearchParams {
  const values: Record<string, string> = {
    a: state.albumAId,
    b: state.albumBId,
  };
  if (state.mode !== DEFAULT_MODE) values.mode = state.mode;
  const params = new URLSearchParams();
  for (const key of PARAM_ORDER) {
    const value = values[key];
    if (value !== undefined) params.set(key, value);
  }
  return params;
}

/** Reads a single `a` param, for a "come here with one side already
 * chosen" link (album/contributor pages' "try connecting this record"
 * CTAs) -- deliberately additive alongside `parseConnectUrlParams`, not a
 * replacement: this never triggers a search (there's no `b` to search
 * against), only a picker prefill. Returns `null` when `a` is absent or
 * empty, OR when `b` is present at all (including a self-referential
 * `a === b`) -- that case belongs entirely to `parseConnectUrlParams`'s
 * own "reject, populate nothing" contract, which this function must never
 * quietly override by treating a rejected pair as a valid single-sided
 * one. This function is strictly for a URL that never named a `b` in the
 * first place. */
export function parsePartialConnectUrlParams(
  search: string,
): { albumAId: string } | null {
  const params = new URLSearchParams(search);
  if (params.has("b")) return null;
  const albumAId = params.get("a");
  if (!albumAId) return null;
  return { albumAId };
}

/** Whether `state` names the SAME two records as the current URL --
 * `mode` deliberately excluded. This is the real push-vs-replace test
 * `connect.ts` uses: re-running the identical pair under a different role
 * filter is a REFINEMENT of the same search (`replaceState`, no new
 * history entry for toggling a filter), while a change to either album is
 * a genuinely new destination (`pushState`, a real back/forward stop). */
export function isSameConnectAlbumPair(
  search: string,
  state: ConnectUrlState,
  validModes: ReadonlySet<string>,
): boolean {
  const current = parseConnectUrlParams(search, validModes);
  if (!current) return false;
  return (
    current.albumAId === state.albumAId && current.albumBId === state.albumBId
  );
}
