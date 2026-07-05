# ADR 0026: Exclude Discogs placeholder identities from the one-hop frontier

- **Status:** Accepted
- **Date:** 2026-07-04

## Context

The first real run of `expand-one-hop` (Milestone 5, [ADR contract](../../data/contracts/discogs-onehop-v1.md)) against the real private seed and the full `snapshot=20260601` catalog (19,192,301 releases) aborted on its own `--max-retained-releases` guard: the one-hop frontier would have retained roughly 21% of the entire catalog, far past any reasonable "bounded working set."

Investigating which frontier artists drove this (a read-only DuckDB query mirroring `onehop.py`'s own frontier/retention logic, run against the public catalog only — no private seed content read or published, see `docs/discogs-data/one-hop-hub-artists.md`) found the retained set was dominated by a small number of extremely prolific credited identities. Two of them are not real performers at all: Discogs assigns real, linked artist IDs to its own catalog *placeholders* —

- `artist_id=194`, "Various Artists" — the compilation-album placeholder, credited (as a real, `playable_identity=True` PAN link) on well over a million releases in this snapshot.
- `artist_id=151641`, "Trad." — the placeholder for traditional/anonymous composers (various ANV spellings across releases: "Trad.", "Haitian Traditional", etc.), credited on hundreds of thousands of releases.

A single compilation LP or traditional-song release anywhere in a seed pulls one of these into the frontier, and from there the one-hop expansion — correctly, by its own definition — retains every other release either one has ever touched. That is not a meaningful "one hop from your collection" connection; it's an artifact of Discogs using linkable artist records for non-performer bookkeeping.

The rest of the observed hub artists (mastering/recording engineers like Robert C. Ludwig and Rudy Van Gelder, and heavily-covered songwriters like Lennon/McCartney, Cole Porter, and Richard Rodgers) are real, individual humans legitimately credited on huge numbers of releases. Excluding *them* would be a much bigger and more subjective call about what counts as a "meaningful" credit — out of scope here.

## Decision

`expand_one_hop`'s frontier query (pass 1 of 2 in `onehop.py`) excludes a small, fixed set of known Discogs placeholder identities via a new `_NON_PLAYABLE_HUB_ARTIST_IDS` constant (`{194, 151641}`), in addition to the existing `playable_identity` (linked-artist) filter. These identities can still appear as *evidence* on any retained release's credit rows (evidence completeness is unaffected — only frontier *membership*, and therefore what they can *retain*, changes); they just never themselves become a hop that pulls in other releases.

This is deliberately narrow: only identities that are Discogs' own non-performer placeholders are excluded, by explicit ID, with the reasoning recorded inline in the code and in `docs/discogs-data/one-hop-hub-artists.md`. Real prolific humans are not excluded, and there is no generic "exclude anyone above N credits" mechanism — that would silently change which real people count as connections without a clear, individually-justified reason, which this project's evidence rules (`AGENTS.md`: "do not infer artistic influence, relationships, or intent from a shared credit") argue against doing casually.

## Consequences

`docs/contracts/discogs-onehop-v1.md`'s frontier definition now has this documented exception. `packages/catalog/tests/test_onehop.py` gained a synthetic test (`test_placeholder_hub_artists_excluded_from_frontier`) proving a placeholder-only release does not get retained via a hub identity, while a real artist on the same release still works normally. The exclusion list lives in one place (`onehop.py`), so extending it later (if another Discogs placeholder identity turns out to cause similar explosions) is a one-line, well-commented change, not a query rewrite. This does not change `playable_identity` itself, `graph-core`, `challenge.py`, or anything else that reads the parsed dataset directly — it is scoped entirely to one-hop frontier construction.

## Validation

`make check` green (134 tests, up from 133) after adding the fixture releases and test. Verified against the real dataset: a read-only diagnostic query (not committed, run ad hoc this session) confirmed `artist_id=194` alone accounts for roughly a third of the original 4.12M-release retained set. The real `expand-one-hop` run was re-executed after this fix; see `docs/BUILD_PLAN.md`'s Milestone 5 update for the resulting real retained-release count.

## Revisit trigger

Revisit if a future real run (a different seed, or a future snapshot) still hits the `--max-retained-releases` guard after this exclusion — that would mean another placeholder-style identity needs the same treatment, or that the guard needs to move from "which identities count" to a different mechanism (e.g. bounding by credit *role*, not by artist identity). Revisit if `graph-core` or `challenge.py` ever need the same hub-suppression for their own graph traversal, since today this exclusion is local to `onehop.py` only.
