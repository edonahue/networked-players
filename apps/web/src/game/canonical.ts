// Canonical JSON serialization and content hashing -- a TypeScript port of
// packages/contracts/src/networked_players_contracts/canonical.py, not a
// structurally-similar reimplementation: both must produce byte-identical
// canonical strings for the same value (keys sorted at every nesting level,
// no insignificant whitespace, non-ASCII left as literal UTF-8 rather than
// escaped) so a content hash computed in either language agrees. See ADR
// 0043's corrective-slice-4.6 addendum.
//
// Used client-side to verify a fetched round's `round_content_fingerprint`
// against what a frozen daily-manifest entry expects, without trusting the
// server not to have silently changed the round underneath an already-
// shared date.

/** A deterministic JSON string: keys sorted at every nesting level, no
 * insignificant whitespace. Matches Python's
 * `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  const parts = keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`);
  return `{${parts.join(",")}}`;
}

async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** A truncated sha256 hex digest of `value`'s canonical JSON form. Matches
 * `networked_players_contracts.canonical.content_hash`. Async: browsers only
 * expose SHA-256 via the (async) SubtleCrypto API. */
export async function contentHash(value: unknown, length = 16): Promise<string> {
  const digest = await sha256Hex(canonicalJson(value));
  return digest.slice(0, length);
}

/** Matches `networked_players_graph_core.connection_rounds
 * ::round_content_fingerprint` / the dependency-free mirror in
 * `networked_players_contracts.connection_rounds`. */
export async function roundContentFingerprint(round: unknown): Promise<string> {
  return `rfp-${await contentHash(round, 16)}`;
}
