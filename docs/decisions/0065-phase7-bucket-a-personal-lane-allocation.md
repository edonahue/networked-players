# ADR 0065: Phase 7 Bucket A allocation — 13 personal, not 16

- **Status:** Accepted
- **Date:** 2026-08-27
- **Depends on:** [ADR 0011](0011-private-seed-contract.md) (private seed / editorial intent boundary), `data/contracts/editorial-seed-v1.md`, the mission brief's Bucket A instructions

## Context

Phase 7's mission brief specified 16 personal/editorial anchors across three lanes: a five-album Jamiroquai core run, five Disney-jazz/exotica picks, and six classic/alternative guitar-centered records — with named reserves for any pick that failed policy, and an explicit instruction not to substitute silently.

Resolving the full 16-query list against the real `20260601` snapshot with `resolve-editorial-albums` (PR #145's new tool) found **three, not two, real policy failures**:

1. **Louis Armstrong — *Disney Songs the Satchmo Way*** (master 265717): master genres include `Stage & Screen`; excluded by `album_policy._NON_STUDIO_GENRES`. Found during planning, before this tool existed.
2. **Les Baxter — *Ritual of the Savage*** (only master 1161698): exists only as a 1995 twofer CD (`Tamboo! / The Ritual Of The Savage`), 1–2 variants, no clean studio-album master. Its named reserve, Esquivel — *Other Worlds, Other Sounds* — is not resolvable either: the artist is absent from the `20260601` snapshot entirely, confirmed by direct query (`lower(name) IN ('esquivel','esquivel!')` returns zero credit rows in the full snapshot). Found during planning.
3. **The Dave Brubeck Quartet — *Dave Digs Disney*** (master 110093): **found only by actually running the resolver**, not by hand-checking. Its master genres also include `Stage & Screen` — the identical automatic exclusion that caught the Armstrong pick, for the same underlying reason (Discogs classifies Disney-song-cover jazz albums as Stage & Screen regardless of performer). `resolve-editorial-albums`'s own output: `"reason": "non-studio master: non_studio_master_genre_style: stage & screen"`.

This is exactly the situation ADR-worthy: a real, measured, second instance of the same exclusion this project's earlier planning had only caught once. A hand review missed it; running the actual tool against the actual data did not.

## Decision

**No substitution. 16 − 3 = 13 personal slots.** The three freed slots move to the graph-rich bucket (18 → 19 is not correct either — see the correction below).

The three drops, with reasons, are recorded once here so they are not silently re-investigated in a future phase:

| Dropped | Master | Reason |
|---|---|---|
| Louis Armstrong — *Disney Songs the Satchmo Way* | 265717 | `Stage & Screen` genre — automatic exclusion |
| Les Baxter — *Ritual of the Savage* | 1161698 | No clean studio-album master (twofer only); reserve (Esquivel) absent from snapshot |
| The Dave Brubeck Quartet — *Dave Digs Disney* | 110093 | `Stage & Screen` genre — automatic exclusion, same rule as the Armstrong drop |

**Correction to this PR sequence's own earlier record.** A prior in-conversation planning note (recorded only in agent working notes, never committed) proposed 13/19/8 by inventing a third cut — dropping *Violator* from the guitar lane — reasoning from only two confirmed failures and a miscounted arithmetic. That reasoning was wrong on two counts: Esquivel was always a *reserve*, not a sixteenth slot, so the correct count from two failures would have been 14, not 13; and no third cut was justified at that time. The real third failure (Brubeck) was found afterward, by running the tool, which is what makes 13 the correct number now — for the right reason, not the invented one. The guitar lane is untouched: all 6 requested albums (Revolver, Axis: Bold As Love, Sign "O" The Times, In Rainbows, Violator, Blood Sugar Sex Magik) resolved cleanly and are committed as-is.

**Lane composition of the committed 13** (`data/albums/editorial-seed-v1.json`):
- Jamiroquai core run: 5 of 5 — Emergency On Planet Earth, The Return Of The Space Cowboy, Travelling Without Moving, Synkronized, A Funk Odyssey.
- Disney jazz / exotica: 2 of 5 — Martin Denny *Exotica*, Arthur Lyman *Taboo*. The lane is now exotica-only; its Disney-jazz half has no surviving member. Not a gap this ADR closes — Bucket C's coverage-gap analysis is free to note it if the measured gaps happen to point there, but this ADR does not manufacture a replacement pick to preserve a thematic label.
- Classic / alternative guitar: 6 of 6 — untouched.

**Allocation: 13 personal / 19 graph-rich / 8 coverage-gap = 40.**

## Resolution detail

All 13 resolved by `master_id` pin, sidestepping Discogs' own punctuation inconsistency (`Sign "O" The Time` vs. the artist's actual `Sign "O" The Times` — the master title itself carries the typo). Every pin's artist was independently re-verified against the release's own billed credits (PR #145's mismatched-identity guard) before being accepted. `A Funk Odyssey`'s Discogs master title is literally `2001 A Funk Odyssey`; queried and resolved correctly by ID regardless.

Full resolution log: `resolve-editorial-albums --dataset local/processed/discogs/snapshot=20260601 --masters-root <masters> --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json`, run against the coordinator's full parsed snapshot (not the one-hop working set — these albums are precisely the ones the one-hop working set cannot reach; see `data/contracts/editorial-seed-v1.md`).

## Consequences

- `data/albums/editorial-seed-v1.json` is committed with exactly these 13 albums. It reveals editorial intent, not private collection membership (per the contract's own privacy invariant, tested in PR #145).
- Bucket B (graph-rich) grows from 16 to 19 slots. This raises, not lowers, the bar the working-set expansion (PR B, #145) has to clear — the mission brief's own instruction was that this bucket already couldn't be filled from the pre-expansion candidate pool at 16; 19 is a strictly harder target. The plan's own risk note already flagged this as the one projected-not-measured assumption in the sequence; the next PR's first action verifies it against the real widened corpus, and if it still comes up short, the honest fallback is to shift the shortfall to Bucket C rather than lower the policy bar.
- Bucket C (coverage-gap) stays at 8, unaffected.

## Alternatives rejected

- **Force a same-lane substitute for Dave Digs Disney.** No candidate was investigated for this because the pattern (drop and reallocate, don't force) was already established by the first two drops and reaffirmed as the right call by the owner.
- **Leave the Disney-jazz lane label but repurpose it.** Renaming the lane after the fact to just "classic exotica" was considered and rejected as unnecessary — the album list is what ships, not the label; this ADR records the true composition honestly instead.

## Revisit trigger

If a future snapshot re-parse (a new monthly dump) changes Discogs' own genre/style tagging for either dropped master, or if Esquivel is added to a future dump, re-run `resolve-editorial-albums` against the new snapshot before assuming this allocation still holds.

## Validation

- `resolve-editorial-albums`'s own output for the 16-query run: `resolved_count: 13, unresolved_count: 1` (the Brubeck drop; the two earlier drops were never in the query list submitted to the tool, having already been identified by hand before PR #145 existed).
- `editorial_seed_failures(payload) == []` against the committed `data/albums/editorial-seed-v1.json`.
- Every resolved album's `artist_id` matches its billed credit on the real snapshot (PR #145's mismatched-identity guard ran on every one of the 13).
