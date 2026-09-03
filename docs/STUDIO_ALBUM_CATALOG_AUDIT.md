# Studio-album catalog audit (corrective slice 4.5, 2026-07-20)

Full per-album audit of the real, published 140-album catalog
(`apps/web/public/data/challenge.v2.json`, `snapshot=20260601`), triggered by two
concrete leaks the operator found by inspection: *Eat A Peach* (mixed live/studio)
and *We Are The World* (charity/various-artists single). The existing
`studio-album-v1` policy (release-format descriptors + master genre/style gate)
and the `studio-album-master-exclusions-v1.json` backstop deny-list (ADR 0035/0036
posture: human curation is the backstop for un-separable cases) had already
caught the *structurally signaled* cases (soundtracks, pure live albums with a
`Live` format descriptor). Both leaks share the same gap the two pre-existing
deny-list entries (*Hot August Night*, *The Last Waltz*) already documented:
**zero structured Discogs signal** — no `Live`/`Compilation` format descriptor on
any working-set pressing, no matching master genre/style.

> **Machine-readable companion (corrective slice 4.6; renamed and scoped
> honestly in slice 5.1).** This document is a narrative writeup; it is not
> itself a verifiable, provably-complete record.
> [`docs/data/studio-album-catalog-inclusion-audit-v1.json`](data/studio-album-catalog-inclusion-audit-v1.json)
> (`networked-players-catalog build-album-catalog-audit`) is the committed,
> one-row-per-**included**-album machine-readable artifact this document
> summarizes: every current catalog album's `master_id`, `selection_source`
> (editorial/generic_candidate), `release_format_policy_result`,
> `master_genre_style_result`, `deny_list_status`, `automated_flags`,
> `manual_disposition`, and `final_eligibility`, tied to a `catalog_version`.
>
> **This is an inclusion ledger, not an accept-and-reject decision ledger.**
> A master excluded by the format policy, the genre/style gate, or the
> curated deny-list never gets a row here — for those decisions and their
> reasoning, see
> [`data/albums/studio-album-master-exclusions-v1.json`](../data/albums/studio-album-master-exclusions-v1.json)
> directly. `validate-album-catalog-audit` proves exact 1:1 correspondence
> with the published catalog at `make check` time — every catalog album has
> exactly one audit row, and every audit row's album is actually in the
> catalog. This is a **point-in-time** artifact: a future catalog
> regeneration (new snapshot, new target count, a policy change) requires a
> new audit, both this document and the JSON.

## Method

Automated pass over all 140 albums, cross-referencing:

1. **Title pattern** — regex for `live`, `unplugged`, `soundtrack`, `original
   (motion picture|cast|score)`, `anthology`, `greatest hits`, `best of`, `box
   set`, `bootleg`, `remix(es)`, `b-sides`, `rarities`, `collection`, `sampler`,
   `compilation`.
2. **Artist-credit compilation marker** — artist field literally `Various` /
   `Various Artists`.
3. **Master genre/style** — `Soundtrack` in styles, or `Stage & Screen` in
   genres (mirrors `album_policy.py`'s automatic gate; a positive here would
   indicate the automatic gate itself had a bug, not a new finding).
4. **Mixed live/studio signal** — any working-set pressing carrying a `Live`
   format descriptor, counted against the total (a *pure* live album is already
   excluded upstream; a *nonzero-but-not-all* count would indicate a mixed
   live/studio release the format gate might average away).

Result: **zero** of the 140 albums tripped any of the four automated checks —
confirming the two known leaks (and, on manual inspection below, two more) are
not a bug in the automated gate; they are real instances of the same
"no structured signal at all" class the deny-list already exists for.

## Manual title-by-title review

Every album's title and artist were then read by a human-equivalent pass
(cultural/discography knowledge, not a structured signal) looking specifically
for live, mixed live/studio, or various-artists/charity-compilation albums the
regex/genre checks above cannot catch by construction. Four albums were
flagged; the remaining 136 were not:

| Master ID | Title | Artist | Finding | Disposition |
|---|---|---|---|---|
| 17245 | Eat A Peach | The Allman Brothers Band | Mixed live/studio (3 sides live, 1 studio) | **Excluded** (added to deny-list) |
| 19956 | We Are The World | USA For Africa | Charity single/various-artists project, not a studio album by one act | **Excluded** (added to deny-list) |
| 68141 | Friday Night In San Francisco | Paco De Lucía | Live album (guitar trio concert, Warfield Theatre, 1980) | **Excluded** (added to deny-list) |
| 62619 | Rattle And Hum | U2 | Mixed live/studio, companion to a concert documentary film | **Excluded** (added to deny-list) |

All four: verified against real structured data before exclusion (see each
entry's `reason` in `data/albums/studio-album-master-exclusions-v1.json`) —
0 `Live`/`Compilation` descriptors across every working-set pressing (96–392
pressings each), no matching master genre/style, no title token a regex could
key on. Consistent with the existing two deny-list entries' documented pattern.

No other album in the 140-title catalog matched a live, mixed live/studio,
compilation/anthology/charity-collection, soundtrack/score, EP, remix, box-set,
or bootleg profile on this pass. Several titles that could plausibly be
mistaken for compilations on name alone were checked and confirmed to be
genuine studio albums: *Genius Loves Company* (Ray Charles — a studio album of
newly recorded duets, not a compilation), *Merry Christmas* (Mariah Carey — an
original studio holiday album), *Unforgettable... With Love* (Natalie Cole — a
studio album of new recordings), self-titled debuts (*Elvis Presley*, *Ramones*,
*Whitney Houston*, *Cher*, *Lionel Richie*, *Christopher Cross*, *Vampire
Weekend*, *Tracy Chapman*, *America*, *Blood, Sweat And Tears*), and
unusually-titled studio albums (*Untitled* — Led Zeppelin IV's own official
title; *In The Court Of The Crimson King (An Observation By King Crimson)*).

## Regeneration

The catalog, `challenge.v2.json`, and both Connection Guesser artifacts were
regenerated after this audit with all four new exclusions applied (see the
corrective-slice-4.5 PR comment for before/after counts). A manual leak grep
for all six deny-list titles plus the audit's title-pattern regex against the
regenerated catalog is part of this slice's validation.

## Revisit trigger

This audit is a point-in-time pass over the specific 140-album catalog live at
`snapshot=20260601`. Any future catalog expansion (a larger target count, a new
snapshot, or a policy change admitting different candidates) must re-run this
audit — the deny-list's whole reason for existing is that these categories are
*not* structurally detectable, so a new candidate silently entering the catalog
without a human pass could reintroduce exactly this class of leak.

## Addendum: Phase 7 re-audit (2026-08-30, second cleanup pass)

Phase 7's catalog expansion (PR #161, 140 → 179 albums) triggered this document's
own revisit clause above, but no manual re-check was recorded anywhere at the
time — the automated companion JSON (`docs/data/studio-album-catalog-inclusion-audit-v1.json`)
was regenerated and reported zero flags, but that is the same automated check this
document's own thesis says cannot catch the leak class it exists to guard against
(zero structured Discogs signal). This addendum is that overdue manual pass, run
against the real committed audit record.

**Scope**: every one of the 39 albums added since the 140-album baseline, pulled
directly from the committed audit JSON by `selection_source != "already_published"`:
13 `editorial` (Bucket A, ADR 0065 -- ADR 0069 decided the public record must
never name the personal-collection source, so `build_album_catalog_audit`
now emits `editorial` here; the committed JSON's rows still literally read
`personal_editorial` until the next real regeneration, which needs the
masters dataset on the coordination host), 18 `graph_rich` (Bucket B), and 8
`coverage_gap` (Bucket C) — 13 + 18 + 8 = 39, matching 179 − 140 exactly.

**Method**: identical to the original pass above — every new album's title and
artist reviewed for the same four categories (live, mixed live/studio,
various-artists/charity-compilation, soundtrack/score/box-set/remix/anthology/
b-sides/rarities/bootleg), using cultural/discography knowledge rather than a
structured signal, exactly as the original manual title-by-title review did.

**Result: zero leaks found** among the 39, consistent with the automated
companion JSON's own zero flags for these rows. Three titles are worth
recording explicitly, matching this document's own established practice of
calling out a title that could be misjudged on name/discography alone, then
confirming its real disposition:

- *Club Classics Vol. One* (Soul II Soul, 1989 per the committed catalog) —
  their original studio debut, not a hits compilation despite "Classics" in
  the title.
- *Introducing The Hardline According To Terence Trent D'Arby* (Terence Trent
  D'Arby) — his debut studio album, not a "best of"/retrospective despite
  "Introducing."
- *Ricky Martin* (Ricky Martin, 1999) — a genuine, distinct studio album, but
  **not** his career debut: it is his fifth studio album and first
  English-language one, following four earlier Spanish-language albums
  (including a different, earlier self-titled *Ricky Martin*, 1991). Clean as
  a studio album on its own merits; the self-titled-debut precedent below does
  not apply to it.

The remaining self-titled albums among the 39 (The Specials, Rickie Lee
Jones, Stephen Stills, Bon Jovi) genuinely are each artist's debut and are
clean by the same self-titled-debut precedent this document's original pass
already established for *Elvis Presley*, *Ramones*, *Whitney Houston*, and
others. No other album among the 39 matched a live, mixed live/studio,
compilation/anthology/charity-collection, soundtrack/score, EP, remix,
box-set, or bootleg profile on this pass.

**No catalog or deny-list change resulted** — this pass found nothing to
exclude. `data/albums/studio-album-master-exclusions-v1.json` is unchanged (still
its original 6 entries). This addendum satisfies the revisit trigger above for
Phase 7's specific expansion only; a future catalog expansion still needs its own
re-audit, per that trigger.
