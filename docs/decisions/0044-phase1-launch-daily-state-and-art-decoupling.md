# ADR 0044: Phase 1 launch — pre-launch daily state and presentation-art decoupling

- **Status:** Accepted
- **Date:** 2026-07-21
- **Relates to:** [ADR 0041](0041-frozen-append-only-daily-manifest.md), [ADR 0043](0043-connection-guesser-corrective-slice.md)

## Context

PR #44 (slices 1–5.1) is ready to merge to `main` and auto-deploy the real-data product
(real 140-album catalog, Connection Guesser, frozen 90-date Connection of the Day
manifest) to `networked-players.com`, which today still serves the old synthetic
placeholder. Two decisions must be recorded before merging, because both shape frozen,
publicly-committed content and both have a hard timing constraint tied to the daily's
first scheduled date, **2026-08-01**.

## Decision 1 — pre-launch daily shows a friendly "upcoming" state, not an error

The committed manifest starts `2026-08-01`; merging lands it ~11 days early. Rather than
migrate the schedule's calendar labels (which would rewrite committed content and re-enter
the fingerprint/version machinery for no product benefit), the frontend distinguishes
three cases against a valid, fetched manifest:

- **local date < `start_date`** → a distinct `data-phase="upcoming"` state: a friendly
  "Connection of the Day launches August 1" message, a polite (not assertive) live-region
  announcement, and no gameplay control active. It is **not** an error state.
- **local date within the scheduled range** → play the frozen round (unchanged).
- **local date > the last scheduled date** → an `data-phase="error"` "the schedule needs
  extending" state, distinct copy from the upcoming state.

ISO `YYYY-MM-DD` labels compare correctly as strings, so no `Date` parsing is needed for
the boundary. This preserves every committed round ID, fingerprint, `artifact_version`, and
date→round_id assignment — zero frozen content changes — and keeps the append-only
guarantee intact. A hub `note="First puzzle August 1"` keeps the play hub honest (the card
links to a friendly upcoming page, never a dead link or a broken error); a trivial
follow-up removes the note after launch.

**Rejected:** a one-time prelaunch date-relabel migration. It rewrites the committed
manifest for no benefit while the daily simply hasn't started, and re-opens the
fingerprint/version surface unnecessarily.

## Decision 2 — decouple presentation art from frozen round content

`GameRound` currently embeds an `art` field inside every `endpoints[]`/`middle` album
reference, and `round_content_fingerprint` hashes the **whole** round including `art`.
Today all round art is `null` and 0/140 catalog albums carry `cover_image`. Therefore the
planned slice-7 cover-art enrichment would, as designed, change **every** round
fingerprint → the pool's `artifact_version` → break every frozen daily manifest entry
(both `version-mismatch` and per-date `fingerprint-mismatch`). That is unacceptable once
any daily date is public history.

**Decision:** cover art becomes a **separately versioned public registry keyed by canonical
album ID** (e.g. `apps/web/public/data/catalog/album-art.v1.json`, its own `art_version`,
hotlink `uri150`/`uri`). Rounds and the universe keep stable album IDs and semantic display
fields (title/act/year) but **drop the embedded `art` payload**. The browser resolves art
by ID at render time, falling back to the polished placeholder when a lookup is missing —
**a missing art lookup can never block gameplay**. With art removed from the hashed content,
`round_content_fingerprint` and `artifact_version` become permanently insensitive to
cover-art changes, so all future enrichment leaves frozen daily content untouched.

**Timing / cutoff.** Removing `art` from frozen rounds changes fingerprints **once**. That
one regeneration (which preserves every date→round_id, recomputes fingerprints, and
re-emits the manifest) is a documented, one-time **prelaunch cutover** and must land
**before 2026-08-01** — before the first daily date is public and while the daily shows the
upcoming state, so no played date is affected. **After 2026-08-01 this fingerprint-changing
regeneration is forbidden**; from then on art lives only in the registry and never touches
frozen content.

**Scope note.** This ADR only *records* Decision 2. No art code, contract change, or
regeneration ships in the Phase 1 pre-merge patch. Implementation is slice 7a (the art-
registry cutover), scheduled immediately after the Phase 1 merge with the hard pre-Aug-1
deadline, ahead of slice 7b (actual enrichment).

**Rejected alternatives:** (2) regenerate universe/rounds/manifest *after* enrichment —
works only in a shrinking pre-launch window and re-opens the risk on every future art
change; (3) enrich only unscheduled/non-daily rounds — produces visibly inconsistent art
across surfaces and grows operational complexity. Only the registry (Approach 1) removes
the coupling structurally rather than time-boxing it.

## Consequences

- The daily is safe to ship ~11 days before its first date without rewriting any frozen
  artifact.
- Slice 7 gains a mandatory first sub-step (7a) with a firm 2026-08-01 deadline; slice 7b
  (enrichment) then never risks frozen daily content.
- `AlbumRef`/`GameAlbum`, `game-universe-v1`/`game-rounds-v1` contracts, the synthetic test
  fixture, and `renderSleeve` all change in slice 7a, plus a new `album-art-v1` contract.
