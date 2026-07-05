# One-hop hub artists (real-data investigation, 2026-07-04)

The first real run of `expand-one-hop` (Milestone 5) against the real private seed and
the full `snapshot=20260601` catalog aborted on its own `--max-retained-releases` guard:
the one-hop frontier would have retained roughly 21% of the entire 19,192,301-release
catalog. This document is the investigation into why, grounded entirely in public,
catalog-wide data — **no private seed content (which releases, how many, or any seed
aggregate like a count or hash) is used or published here.**

## Method

The one-hop frontier (`onehop.py`'s pass 1) selects every artist with a *playable*
(linked) credit on a seed release. For each artist that ends up in a frontier, the
number of *other* releases they're credited on is a pure, seed-independent property of
the public credits table:

```sql
SELECT artist_id, any_value(anv) AS sample_anv, count(DISTINCT release_id) AS credited_release_count
FROM read_parquet('local/processed/discogs/snapshot=20260601/table=credits/*.parquet', hive_partitioning = false)
WHERE playable_identity
GROUP BY artist_id
ORDER BY credited_release_count DESC
```

This is the same aggregation `onehop.py` itself performs internally during pass 2
(retention) for whichever artists land in a given frontier — run here read-only, ad hoc,
against the whole table, with results reported only as public artist-level statistics
(Discogs artist ID, a sample display name, and a release count — all things anyone with
the same public monthly dump could reproduce). `anv` (the display name on a given credit)
varies across a prolific artist's many credits, so the sampled name shown per row is only
one of possibly several real spellings for that same `artist_id`.

## Findings: two placeholders, everything else real

Of the top 100 artists by credited-release count, exactly two are not real performers —
they are Discogs' own catalog placeholders, which nonetheless carry a real, linked
`artist_id` (`playable_identity=True`):

| `artist_id` | Sample ANV | Credited releases | % of catalog | What it is |
| ---: | --- | ---: | ---: | --- |
| 194 | Various Artists | 1,341,475 | 6.99% | Discogs' compilation-album placeholder |
| 151641 | Trad. / Haitian Traditional | 216,713 | 1.13% | Discogs' placeholder for traditional/anonymous composers |

Together, these two identities alone touch roughly 8% of the entire catalog. A seed
containing even one compilation LP or one traditional-song release is enough to pull one
of them into the frontier — and from there, correctly by the one-hop definition, every
other release either has ever touched gets retained. That's a data-modeling artifact, not
a meaningful "one hop from your collection" connection.

The rest of the top 100 (ranks 3–100, all individually reviewed) are real, historical
human contributors, dominated by two categories:

- **Heavily-covered songwriters**, credited on every recorded version of their
  compositions: Lennon/McCartney, Bob Dylan, Duke Ellington, Cole Porter, Johnny Mercer,
  Irving Berlin, Chuck Berry, Rodgers & Hart, Leiber/Stoller, Gershwin, Bacharach/David,
  Holland–Dozier–Holland, and dozens more.
- **Extremely prolific mastering/recording engineers**, credited on releases across many
  unrelated artists and genres: Robert C. Ludwig, Rudy Van Gelder, Bernie Grundman, Ted
  Jensen, Bob Clearmountain, Doug Sachs, Tom Dowd, and others.

A representative sample of the largest real hubs (ranks 3–20):

| `artist_id` | Representative name | Credited releases |
| ---: | --- | ---: |
| 779927 | Lennon/McCartney | 87,085 |
| 59792 | Bob Dylan | 60,964 |
| 271098 | Robert C. Ludwig (mastering engineer) | 59,398 |
| 145257 | Duke Ellington | 54,798 |
| 264026 | Cole Porter | 52,837 |
| 164574 | Johnny Mercer | 48,947 |
| 27518 | Elvis Presley | 45,291 |
| 508131 | Irving Berlin | 44,652 |
| 18956 | Stevie Wonder | 41,909 |
| 252966 | Rudy Van Gelder (recording engineer) | 41,719 |
| 82730 | The Beatles (Cyrillic ANV) | 40,651 |
| 180119 | Chuck Berry | 40,308 |
| 604171 | Rodgers and Hart | 33,772 |
| 10263 | David Bowie | 33,267 |
| 57103 | Elton John | 33,002 |
| 307942 | Bernie Grundman (mastering engineer) | 32,984 |
| 335003 | George Merino (mastering engineer) | 32,521 |
| 259758 | Ted Jensen (mastering engineer) | 31,560 |

These are legitimate, if broad, credited connections — a real person, really credited.
Excluding entire *identities* like these would be a much bigger and more subjective call
about what counts as a "meaningful" connection for the game. Excluding by *role* instead
— see below — turned out to be the better lever.

## Role-based filtering: a better lever than excluding identities

With the two placeholders excluded (ADR 0026), the real run still retained 2,999,567
releases (~15.6% of the catalog) — the real hub artists above were still pulling in a
large volume. A second investigation checked *how* they were connecting: by role, not
just by identity.

For the top ~20 real hub artists, credits split into:

- **180,357** distinct releases connected via a **main-artist credit** (no role at all —
  the artist literally *is* the release's listed artist). This is the most legitimate
  connection type there is; role-based filtering cannot and should not touch it.
- **619,516** distinct releases connected via a non-null "extra artist" role credit, of
  which **585,836** were attributable *only* to a role classified as pure
  production/writing/business (Written-By, Mastered By, Producer, Engineer, Arranged By,
  etc. — no performer role mixed in, checked against **3,115 distinct role-text
  variants** observed for just these 20 artists; `role_text` is freeform and
  comma-combined, e.g. "Producer, Mixed By, Arranged By").

That is: the large majority of these artists' hub-ness (outside their own main-artist
credits) comes from being credited as an engineer, writer, or producer on someone else's
release — not from performing on it. That's a real, structural distinction `role_text`
already encodes, not a guess.

## Decision

Two exclusions apply to one-hop frontier/retention eligibility (never to evidence — every
credit row of a retained release still survives regardless):

- The two Discogs placeholder identities (194, 151641) — [ADR 0026](../decisions/0026-exclude-placeholder-artists-from-one-hop-frontier.md),
  `_NON_PLAYABLE_HUB_ARTIST_IDS` in `onehop.py`.
- Credits whose role is *purely* non-performer (every comma-separated role component
  matches a fixed token list; a main-artist credit or any mixed-in performer role always
  stays eligible) — [ADR 0027](../decisions/0027-exclude-non-performer-roles-from-one-hop-frontier.md),
  `_NON_PERFORMER_ROLE_TOKENS` in `onehop.py`. "Producer" is included on this list, which
  is the most debatable entry — see ADR 0027 for why, and how to change it later.

Real prolific humans are not excluded as *identities* — David Bowie, Bob Dylan, and the
mastering engineers above still count fully via their real performer/main-artist credits.
Only their purely-administrative credits elsewhere stop counting as a hop.

## Result: the real run, before and after

The real `expand-one-hop` run against the operator's actual private seed (size/contents
never published), before and after each fix:

| Stage | Retained releases | % of catalog | Frontier artists |
| --- | ---: | ---: | ---: |
| Before any exclusion (aborted, nothing written) | 4,121,127 | 21.5% | — |
| After placeholder-identity exclusion (ADR 0026, aborted, nothing written) | 2,999,567 | 15.6% | — |
| After placeholder + role exclusion (ADR 0027, succeeded) | **1,410,106** | **7.3%** | **1,762** |

The final real output is 868 MB (releases 21 MB, tracks 190 MB, credits 657 MB) and passed
`networked-players-catalog validate` with zero orphan/invalid counts. See
`docs/DATA_SIZING.md` for this recorded as an observed measurement and
`docs/BUILD_PLAN.md`'s Milestone 5 for the narrative update.

## Revisit

If a future real run (a different seed, or a later snapshot) still hits the
`--max-retained-releases` guard after both exclusions, re-run the queries above against
the new snapshot: check ranks beyond 100 for another placeholder-style identity, or
reconsider whether "producer" belongs on the non-performer role list, or whether treating
credit *counts per role category* (rather than a binary include/exclude) is needed. A
Jupyter notebook with runnable versions of every query in this document is planned as a
follow-up so this kind of investigation doesn't require re-deriving the SQL from scratch
each time (not built yet).
