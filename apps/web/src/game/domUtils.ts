// Small, dependency-free DOM/browser-API helpers duplicated verbatim
// across several game modules before this file existed (post-Phase-4
// cleanup audit F13) -- `escapeHtml` in connect.ts/connectEvidence.ts/
// contributorsDirectory.ts/explorerStage.ts, `sessionStorageOrNull` in
// connect.ts/contributorsDirectory.ts/explorerStage.ts. Consolidated here
// so a future fix to either only needs to happen once.
//
// `StorageLike` (the small `getItem`/`setItem` interface used to inject a
// real or fake storage backend) is deliberately NOT here -- `store.ts` is
// already its canonical source (`flagship.ts`/`dailyArchiveStage.ts`
// already import it from there); this file only picks up the two helpers
// that had no existing canonical home.

/** Escapes the five HTML-significant characters for safe interpolation
 * into `innerHTML` -- every game module that builds markup from untrusted
 * or semi-trusted text (album titles, contributor names) routes through
 * this before interpolating. */
export function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/** `window.sessionStorage` can throw (private browsing, storage disabled)
 * merely by being accessed, not just by `.setItem` failing -- this is the
 * one safe way to obtain it, returning `null` instead of throwing so a
 * caller can degrade to an in-memory-only session. */
export function sessionStorageOrNull(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** A consistent "couldn't fetch X" failure message shared across every
 * game mode that has no more specific retry mechanic than reloading the
 * page. Each mode used to spell this out independently -- split roughly
 * evenly between "Couldn't"/"Could not" and three different retry
 * phrasings ("try again", "keep typing to retry", "try reloading"/
 * "try refreshing") for the identical situation. Connect's own
 * catalog-load failure is a real exception, not folded in here: typing
 * in its search box retries automatically, a genuinely different (and
 * more specific) recovery path than reloading the page. */
export function fetchFailureMessage(subject: string): string {
  return `Could not load ${subject} right now — try refreshing the page.`;
}
