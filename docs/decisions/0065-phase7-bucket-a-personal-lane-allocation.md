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

All 13 resolved by `master_id` pin, sidestepping a real Discogs data quirk: `find_release_by_title_artist`'s text match requires an exact match against the raw *release* title, and this dataset's main release for master 52497 is titled `Sign "O" The Time` (missing the final "s") — not the album's actual, correct title. A text query for the correct title would not have matched that release row at all. Pinning by `master_id` sidesteps needing to already know the exact raw string; the *committed* `title` field is correctly `Sign "O" The Times`, taken from the attached master (the canonical source, preferred over the release title precisely because the release title can carry this kind of inconsistency). Every pin's artist was independently re-verified against the release's own billed credits (PR #145's mismatched-identity guard) before being accepted. Master 69925's main release is similarly titled `2001 A Funk Odyssey` on Discogs; the committed `title` again correctly reads the master's own `A Funk Odyssey`.

Full resolution log: `resolve-editorial-albums --dataset local/processed/discogs/snapshot=20260601 --masters-root <masters> --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json`, run against the coordinator's full parsed snapshot (not the one-hop working set — these albums are precisely the ones the one-hop working set cannot reach; see `data/contracts/editorial-seed-v1.md`).

## Consequences

- `data/albums/editorial-seed-v1.json` is committed with exactly these 13 albums. It reveals editorial intent, not private collection membership (per the contract's own privacy invariant, tested in PR #145).
- Bucket B (graph-rich) grows from 16 to 19 slots. This raises, not lowers, the bar the working-set expansion (PR B, #145) has to clear — the mission brief's own instruction was that this bucket already couldn't be filled from the pre-expansion candidate pool at 16; 19 is a strictly harder target. The plan's own risk note already flagged this as the one projected-not-measured assumption in the sequence; the next PR's first action verifies it against the real widened corpus, and if it still comes up short, the honest fallback is to shift the shortfall to Bucket C rather than lower the policy bar.
- Bucket C (coverage-gap) stays at 8, unaffected.
- **Implementation constraint for the catalog-assembly PR (real, found in review, not yet fixable here because the consuming code does not exist yet).** `data/albums/editorial-seed-v1.json` is not wired into `build-public-album-catalog` by this PR or PR #145 — only into `expand_one_hop --additional-seed`, which widens the one-hop *working set*, not the catalog. When catalog assembly is built, it must **not** run Bucket A's entries through `challenge.py::match_albums`, whose `seen_artist_ids` dedup keeps at most one album per `artist_id` (correct for `top-albums-v1.json`'s one-album-per-notable-artist editorial backbone; wrong for Bucket A, which deliberately has five Jamiroquai entries). Naively reusing that path would silently drop four of the five Jamiroquai albums to `missed`, breaking the 13-count and the 5-of-5 claim this ADR makes. Each `editorial-seed-v1.json` entry already carries a resolved, individually-verified identity (`artist_id`/`master_id`/`main_release_id`) — catalog assembly should include Bucket A by that identity directly, re-applying only eligibility policy (format allow-list, master exclusions — both of which can change between resolution time and build time), never artist-level dedup or a second identity search.

## Alternatives rejected

- **Force a same-lane substitute for Dave Digs Disney.** No candidate was investigated for this because the pattern (drop and reallocate, don't force) was already established by the first two drops and reaffirmed as the right call by the owner.
- **Leave the Disney-jazz lane label but repurpose it.** Renaming the lane after the fact to just "classic exotica" was considered and rejected as unnecessary — the album list is what ships, not the label; this ADR records the true composition honestly instead.

## Revisit trigger

If a future snapshot re-parse (a new monthly dump) changes Discogs' own genre/style tagging for either dropped master, or if Esquivel is added to a future dump, re-run `resolve-editorial-albums` against the new snapshot before assuming this allocation still holds.

## Validation

- `resolve-editorial-albums`'s own output for the 16-query run: `resolved_count: 13, unresolved_count: 1` (the Brubeck drop; the two earlier drops were never in the query list submitted to the tool, having already been identified by hand before PR #145 existed).
- `editorial_seed_failures(payload) == []` against the committed `data/albums/editorial-seed-v1.json`.
- Every resolved album's `artist_id` matches its billed credit on the real snapshot (PR #145's mismatched-identity guard ran on every one of the 13).

## Addendum (2026-08-30)

Bucket B's own risk note above ("this raises, not lowers, the bar... the
next PR's first action verifies it against the real widened corpus, and if
it still comes up short, the honest fallback is to shift the shortfall to
Bucket C") turned out to be exactly the case that materialized: the
committed catalog audit
(`docs/data/studio-album-catalog-inclusion-audit-v1.json`) shows **18**
`graph_rich`-sourced albums against the 19-slot target this ADR set, one
short — confirmed directly, not a counting error (also independently
documented in `docs/NEXT_PATH_BRIEF.md`'s own 2026-08-30 post-Phase-7-audit
correction). Final composition: **13 personal + 18 graph-rich + 8
coverage-gap = 39** published albums (140 pre-Phase-7 + 39 = 179 total),
not the 40 this ADR originally allocated for.

No shortfall reallocation happened either, contrary to this ADR's own
stated fallback plan — the shortfall was simply never revisited during the
PRs that followed (#152–161), and shipped as 179 without anyone noticing
the gap between the 40-slot allocation and the 39 actually assembled until
this closeout's own investigation found it.

**Decision, made during the Phase 7 closeout recovery pass**: accept 179 as
final. No 19th graph-rich candidate is manufactured or force-added to close
the gap, and no filler album is added anywhere else to round the total back
up to 180 or any other number. This is a deliberate closed decision, not an
open question left for a future phase — the closeout plan's own explicit
non-goals list ("no further catalog expansion, no filler album, no new
public artifact generation") applies squarely here, and inventing a 19th
pick after the fact, purely to match a number this ADR itself only ever
called "projected, not measured" risk, would be exactly the kind of
retroactive number-fitting AGENTS.md's sizing-claim discipline exists to
prevent.

If a future phase genuinely wants Bucket B at its originally-planned 19
(or any other real, editorially-justified expansion), that is new catalog
work with its own real candidate evaluation — not a correction to this
ADR, and not something this closeout performs.
