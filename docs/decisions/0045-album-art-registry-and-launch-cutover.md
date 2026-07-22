# ADR 0045: Album-art registry and the art-first daily launch cutover

- **Status:** Accepted
- **Date:** 2026-07-22
- **Refines:** [ADR 0044](0044-phase1-launch-daily-state-and-art-decoupling.md) against the real code
- **Relates to:** [ADR 0043](0043-connection-guesser-corrective-slice.md) (frozen manifest/fingerprints), ADR 0012 (Discogs API cover-art posture)

## Context

Phase 1 shipped the real Connection Guesser + album catalog live, but every
album renders a placeholder — no cover art is enriched. ADR 0044 recorded the
direction (decouple presentation art from frozen game content via a separately
versioned registry, launch the daily on the operator's real go-live date, no
August-1 dependency). This ADR settles the concrete design against the code and
records the implementation decisions.

## Decision 1 — art is resolved by album id from a separate registry; frozen content is art-free

- New public artifact `apps/web/public/data/catalog/album-art.v1.json`
  (`data/contracts/album-art-v1.md`): a presentation-only lookup keyed by
  canonical album id, with `catalog_version` agreement and an order-insensitive
  `art_version`. Not every album needs an entry (missing → placeholder).
- **`SleeveArt` is narrowed to `{kind:"generated"} | null`** — the `hotlink`
  variant is removed, so a cover URL can never live in frozen game content.
  `generated` marks a synthetic SVG sleeve (test fixture only); `null` means
  "resolve a real cover by album id from the registry."
- The generator (`connection_rounds.py::_album_ref` / the universe builder) is
  art-free; both validators (`graph-core` gen-time + the dependency-free
  `contracts` mirror) reject any embedded `hotlink`/`uri` art in frozen
  content. The TS type and both frontends resolve art by id
  (`game/albumArt.ts` at runtime, `data/albumArt.ts` at build time).

**Key finding that simplified the cutover:** the published rounds already
carried `art: null` everywhere (cover art was never enriched), so making the
generator art-free produced **byte-identical** `universe.v1.json` /
`rounds.v1.json` — verified by regenerating and diffing. The art decoupling
therefore required **no frozen-artifact regeneration and no fingerprint
change**; the daily manifest is untouched by 7A. This is stronger than ADR
0044's anticipated one-time fingerprint-changing cutover: art was decoupled
with zero frozen churn.

## Decision 2 — enrichment reuses the existing rate-limited Discogs client

`build-album-art-registry` (operator-only, coordination host) reuses
`discogs/api_client.py` (throttle, 429/`Retry-After`, resumable on-disk cache)
and `discogs/album_art.py`. Deterministic lookup by `main_release_id` — no
fuzzy search, never a wrong pressing to pad coverage. Hotlink URLs only; no
image bytes stored. The public registry is written only after it validates.

## Decision 3 — the daily launches on the operator's real date, not a placeholder

The committed manifest's `2026-08-01` start is a placeholder, **not** a
requirement. The launch cutover re-emits the daily manifest with an explicit
operator-supplied `--start-date` (the real go-live date) and `--generated-at`,
preserving the exact ordered sequence of the same 90 round ids and their
`round_fingerprint`s (which are unchanged, since the rounds are unchanged) —
only the calendar dates and top-level metadata move. This is the **final**
prelaunch date migration; reassignment is prohibited once the first daily is
public. Until then the daily shows the friendly `upcoming` state, whose copy is
derived from the manifest's `start_date` (no hardcoded date in source).

## Consequences

- Cover-art enrichment (7B) and any future art refresh never touch frozen
  fingerprints or the daily manifest — permanently, by construction.
- One art source (`album-art.v1.json`) feeds both the game and browse surfaces;
  `cover_image` on `challenge.v2.json` is legacy and superseded by the registry.
- The launch date is an operator input at cutover time; no August-1 dependency
  remains in code.

## Validation

`make check` (incl. the new `album_art` contract tests, art-free generator +
validator tests, and the byte-identical regeneration proof); `npm run check`;
full Playwright incl. art success / missing / malformed / version-mismatch /
upstream-image-failure → placeholder, and the pre/in/post-range daily states.
The registry is independently re-validatable on the Pi fleet.

## Revisit trigger

If Discogs stops permitting hotlinking, or a future catalog regeneration
changes `catalog_version`, regenerate the registry against the new catalog and
bump `art_version`. If frozen game content ever needs to carry art again, that
is a new ADR — the whole point here is that it must not.
