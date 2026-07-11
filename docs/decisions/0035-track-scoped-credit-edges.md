# ADR 0035: An edge means "contributed to the same recording", not "appears on the same release"

- **Status:** Accepted
- **Date:** 2026-07-10
- **Supersedes:** [ADR 0029](0029-connectivity-scorer-flags-dont-fix-traversal-gap.md)
- **Extends:** [ADR 0026](0026-exclude-placeholder-artists-from-one-hop-frontier.md),
  [ADR 0027](0027-exclude-non-performer-roles-from-one-hop-frontier.md) to the traversal layer

## Context

The local cohort curator was surfacing one-hop album matches that are musically
absurd: Pink Floyd ↔ Nas, Pink Floyd ↔ Kendrick Lamar, Nirvana ↔ John Coltrane,
Prince ↔ Black Sabbath. A forensic audit on 2026-07-10 traced each to its Discogs
rows against the real one-hop corpus (`snapshot=20260601`, 47,621,633 credit rows).

**The identity model was not at fault.** Discogs `artist_id` is parsed at
`releases.py:71`, `playable_identity ≡ is_linked ≡ (artist_id IS NOT NULL)` holds on
all 47.6M rows with zero violations, ANV lives in its own column and is never read
during edge construction, every traversal join is numeric, and **zero names in the
corpus map to more than one `artist_id`** (Discogs disambiguates with "(2)" suffixes).
All 25 albums of the audited cohort resolved via `release_id_hint`, never a name match.

The fault was in `graph.py`'s edge definition. `linked_credits` selected
`(release_id, artist_id)` and `neighbors()` self-joined it on `release_id`. So **any
two artists appearing anywhere on one release were one hop apart.** A 46-track DJ
compilation became a 46-artist clique. `track_index` was parsed, stored in the
parquet, and never referenced.

Three findings made this systemic rather than incidental:

1. **The "Various Artists" guard guarded nothing.** Excluding artist 194 removes one
   vertex from a 46-clique. And release 1304383, *"The Music Machine!"*, is billed to
   a real DJ ("Ruckus Roboticus"), so 194 never appeared at all.
2. **The quality flag was actively misleading.** `classify_hop_quality` graded by
   *role text*. A compilation's track artists carry `role_text = NULL`, so they graded
   as `performer_credit` — the strong flag. `cohort_editorial._pair_score` then awarded
   `+30` (1-hop) `+35` (performer) with no compilation penalty: **the pipeline ranked
   its own false positives highest.** The top suggestion was Pink Floyd ↔ Prince, on
   opposite sides of a Greek promo compilation, scoring 41 with zero warnings.
3. **Shortest-path search selects for the defect.** Compilation-shaped releases
   produced only 26.3% of the graph's edges but carried **91.7%** of the curator's
   paths, because BFS is drawn to the highest-degree edges.

Measured false-positive rate over all 326 evidence hops the curator produced: **~99%**.
Exactly 2 hops put both artists on the same track, and both were bootleg mashups.

A two-hop minimum was tested and rejected: 2-hop pairs were **95%** compilation-borne
vs 91% for 1-hop, and 51 of 57 two-hop pairs were compilation → compilation chains.
Forbidding one hop merely routes through two compilations. Path length is not the
defect; the edge is.

ADR 0029 saw a weaker version of this (placeholder identities and non-performer roles
leaking into `CreditGraph` because `onehop.py`'s exclusions only govern dataset
retention) and chose to flag rather than fix, to avoid disturbing `challenge.py`. That
deferral is now the load-bearing defect, and the deeper container problem it sat on top
of was never identified.

## Decision

`CreditGraph` traverses a new materialized relation, `credit_edges(artist_a_id,
artist_b_id, release_id)`, built by `graph.credit_edges_sql()` — the single edge
definition in the package, reused verbatim by `snapshot.py`. `linked_credits` survives
only to resolve display names and report corpus size; it is never self-joined.

A credit is **edge-ineligible** when its artist is a placeholder or its role is
disqualifying.

**Placeholder identities** live in `placeholder_artists.json` beside `graph.py`, loaded
with `importlib.resources` — data, not code, so the list is reviewable and editable
without a code change. The audit found **31** of them (284,353 release-credits between
them), not the two ADR 0026 knew about: `194 "Various"` (237,271 releases),
`151641 "Traditional"` (29,224), `355 "Unknown Artist"` (10,613), `118760 "No Artist"`
(6,295), `967691 "Anonymous"` (827), and a long tail of Discogs-disambiguated variants
("Unknown (12)", "N/A (7)", "Anonymous (46)"). 355 surfaced in the first post-fix rescore
bridging Pink Floyd to Biz Markie.

Each entry carries a **policy**: `exclude` (never enters `credit_edges`, so it cannot be a
hop endpoint, a curator suggestion, or a site path node) or `flag` (stays traversable, and
`cohort_connectivity` tags every hop through it `placeholder_artist_hop` for review). All
31 are `exclude` pending review. **Filtering is always by numeric `artist_id`**; the names
in the config document the IDs and never select them, because a real band can be called
"Anonymous". `PLACEHOLDER_NAME_PATTERN` and `CreditGraph.placeholder_artist_candidates()`
exist only to *propose* additions for a human to promote when a new snapshot lands.

The disqualifying roles are:

- a **quotation** — a bracketed `[Sample]` / `[Samples From]` / `[Interpolation]` /
  `[Excerpt]` / `[Contains …]` qualifier, or the bare role `Samples` / `Sampled By`.
  The bracket is load-bearing and must not be stripped before matching: `Sampler
  [Fairlight]` is an *instrument* credit and survives, while `Performer [Sample]` does
  not. (`_BRACKET_SUFFIX_RE`, used elsewhere, would have destroyed exactly this signal.)
- **rework** — `Remix` (188,152 rows, 24,519 artists), `Remixed By`, `Edited By`,
  `Re-Edit`, `DJ Mix`, `Mashup`. A remixer takes a finished recording and reworks it; they
  were never in the room. One remixer working across two compilations bridges every artist
  on them — Aaron Scofield (`Remix` on a Strokes track, `Edited By` on a Cure track) was a
  top-10 curator suggestion before this. Not to be confused with **`Mixed By`** (733,088
  rows), which is studio mixing of the original session and stays edge-eligible: that is
  Andy Wallace on *Nevermind*.
- **non-collaborative** — authorship of an underlying composition (`Written-By`,
  `Composed By`, `Songwriter`, …), packaging (`Design`, `Art Direction`, `Photography By`),
  or business/logistics (`Executive-Producer` — 181,979 rows, `Coordinator` — 143,312,
  `A&R`, `Management`, `Supervised By`, `Authoring`). A role qualifies only when *every*
  comma-separated component matches, so `Written-By, Producer` (Butch Vig on *Nevermind*)
  stays eligible. Studio roles — Producer, Engineer, Mixed By, Mastered By, Recorded By,
  Arranged By — are deliberately kept: those people were in the room. This closes
  ADR 0027's gap at the traversal layer for composition credits, which is what made
  "Lennon-McCartney" a 36,857-release hub, "Bob Ludwig" 32,054, and "Traditional" 29,224.
  A *photo coordinator* credited on both *Nevermind* and a Coltrane reissue is what put
  Nirvana two hops from John Coltrane in the first post-fix rescore.

**Two independent compilation guards.** `album_shaped(r)` means *fewer than
`COMPILATION_TRACK_ARTIST_THRESHOLD` (5) distinct `track_artist` identities, and between 2
and `max_artists_per_release` distinct artists*. But a documentary or video compilation has
no `track_artist` rows at all — it names its acts with `Featuring` track credits — so that
guard reads it as a one-artist album. The second guard is the track itself:
`MAX_ARTISTS_PER_TRACK` (16). Distinct edge-eligible artists per track across the corpus
run p50=1, p90=5, p99=14, p99.9=27, max=576; the containers sit at 19 (the *Glastonbury*
DVD), 25 (its reissue) and 314 (*The Work Of Director Spike Jonze*), while every
collaboration verified by hand sits at ≤5. **No rule may read a track above this cap**,
including the fallback below — otherwise a festival film's billed director inherits every
act on the bill.

Let a track's **performers** be its `track_artist` rows, or — when a track has none, the
release is `album_shaped`, *and* it is billed to exactly one artist — that billed artist.
For the curated cohort graph, a track explicitly titled as a **Live**, **Demo**,
**Remix**, **Re-Edit**, **Acoustic**, or **Radio Edit** variant is not eligible for a
track-scoped edge. The normalized snapshot does not retain Discogs format descriptions,
so it cannot authoritatively classify a release as a studio album or a single. This
narrow title-based rule is intentionally only a guard against obvious B-sides, bonus
tracks, and rework evidence; it is not a substitute for a future release-format model.
Three rules produce an edge:

| rule | edge |
|---|---|
| `same_recording` | a track's performers ↔ every other edge-eligible **non-`track_artist`** credit on that same `track_index` |
| `co_performers` | performers of one track ↔ each other, only when `album_shaped` **and both are billed `release_artist`s** |
| `release_scope` | an `album_shaped` release's billed artist ↔ its `release_credit` contributors |

Each is a **star, not a clique**, wherever the clique would be unjustified:

- Two `Featuring` guests on one DVD chapter never touch each other (`same_recording`
  excludes `track_artist`-to-`track_artist`; that is `co_performers`' job).
- A mashup's co-credited track artists never touch. Two guards are needed: a large mashup
  album has ≥5 track artists, but *"Satanik Mashups Vol I"* has only four — so
  `co_performers` additionally requires both performers to be **billed on the release**. A
  duet or split single bills both acts; a bootleg bills the bootlegger ("Inhumanz"), and
  its track "Shoot The War Pigs" co-credits Nas and Black Sabbath, who never met.
- An album's producer, mixer and masterer each connect to the band, never to each other
  (`release_scope` starts from the billed artist only). Without this, a 40-credit album
  is a 780-edge clique.
- `release_scope` excludes `track_artist` credits, so on a bootleg split the billed
  artist does not inherit the other band's tracks.

Hops now carry exactly one **scope flag** (`same_recording` | `release_scope_credit`)
alongside the existing strength flag; the contract validator enforces both.
`SCORER_VERSION` → 4, `GRAPH_SNAPSHOT_SCHEMA_VERSION` → 2 (an edge now names one
deterministic evidence release, not a `release_ids` list). `CreditGraph.credit_row_count`
becomes `degree` — with `credit_edges` materialized, true degree is as cheap as the old
credit-row proxy and is what `max_frontier_expansion` always meant.

Editorial ranking leads with scope rather than role: `+35` when every hop is
same-recording evidence, `+15` when some are, `+10` for `performer_credit`. The
`non_performer_only` penalty drops from `-45` to `-15` — a studio-only link is now a
real, if weaker, connection rather than the container artifact it used to flag.

**`challenge.py` churn is accepted.** ADR 0029 deferred this fix to protect the live
album-centered web experience. `challenge.v2.json` is a generated artifact and is not
yet publicly published; regenerating it is cheap now and expensive later. One correct
graph, one code path.

## Consequences

Measured on the real corpus (`snapshot=20260601`, `max_artists_per_release=50`), and on a
full rescore of the `discogs-community-best-albums` cohort (300 pairs, 25 albums):

- Undirected edges **241,100,565 → 1,765,676**; connected artists 504,267 of 916,873.
  Graph build ~158s at `memory_limit=2GB` on a ZimaBoard.
- **Compilation-borne evidence hops: 91.7% → 0.0%** (0 of 476). Placeholder identities
  appearing in any hop: **0**.
- All four reported false positives are gone as direct edges, as is the old #1 curator
  suggestion (Pink Floyd ↔ Prince via a Greek promo compilation, which scored 41 with zero
  warnings). The new #1 is Nas ↔ Wu-Tang Clan via Nas's `Featuring` credit on "Let My
  Niggas Live" from *The W*.
- Scoring got cheaper as well as truer: peak RSS **1456 MB → 355 MB**, reach rows
  5,067,810 → 160,943, wall time 531s → 142s.
- Path lengths grew, as they should: `easy` (1 hop) **243 → 14**, with the rest at 2–3
  hops. Scores from `scorer_version <= 3` are not comparable.

Known false negatives and residuals, accepted:

- **Co-billed release artists no longer connect.** In the audited sample every co-billed
  pair among famous solo artists was a bootleg, split, mashup or magazine sampler
  (Nirvana ↔ Pearl Jam, Wu-Tang ↔ Beatles, GnR ↔ Nirvana, Pink Floyd ↔ Black Sabbath).
  A genuine duo record ("X & Y") is structurally indistinguishable from a bootleg split
  in this corpus, and the rule costs only ~61k edges. A `master_id`-gated co-billing rule
  is the recorded revisit path if a real duo cohort ever demands it.
- **Bad Discogs source data still leaks.** Neil Young's live bootleg credits "The
  Beatles" as `Performer` on an "A Day In The Life" intro; the bootleg *"2 Worlds
  Collide"* credits Red Hot Chili Peppers as `Co-producer` on the same track as
  track-artist Nas. Both are structurally indistinguishable from a real guest spot or a
  real co-production. No rule can separate them; that is what human curation is for.
- **Release type is not yet modeled.** A title-based track-variant guard excludes an
  explicit live B-side such as The Strokes ↔ Elvis Costello on *Taken For A Fool*, but
  cannot identify every single, live album, compilation, or reissue. The proper future
  solution is to retain and normalize Discogs format descriptions, then add an explicit
  evidence-release policy rather than broadening title heuristics.
- **Reissue mastering bridges everything at two hops.** Bernie Grundman remastered *The
  Wall* and mastered *DAMN.*, so Pink Floyd and Kendrick Lamar are two `release_scope_credit`
  hops apart. Factually true, and he never met either. Mitigated, not removed: "Remastered
  By" now grades `non_performer_only` so such hops are penalised rather than rewarded. The
  recorded revisit path is to require the evidence release be its master's main release.
- **Large ensembles above `MAX_ARTISTS_PER_TRACK`** (a 20-piece orchestral session) lose
  their same-track edges. p99 is 14, so this is rare; the revisit path is to gate on
  release format, which the dataset does not currently parse.
- **Cover-song links are gone**, by explicit choice: RHCP no longer connects to Stevie
  Wonder via "Higher Ground". If those are wanted back, the recorded path is an
  `edge_kind` column (`performed_with` | `wrote_for`), not re-admitting `Written-By`.

## Curator surface

A connection is only reviewable if a human can see why it exists.
`draft-cohort-editorial-review --dataset <one-hop root>` now explains every hop —
release title and year, the shared recording, and each credited artist's original Discogs
role text — and names the **intermediary artists** a multi-hop path routes through. The
local curator renders both albums' cover art, the hop chain, and a breakdown table of
connection counts by credit type.

Two rules keep that surface honest:

- Each credit carries `justifies_edge`, computed by `graph.edge_ineligible_role()` — the
  Python mirror of `_edge_ineligible_role_sql`, held in step by a parity test over both.
  A `Written-By` or `Remix` credit on the shared track is *context*, not evidence; the UI
  dims it and the breakdown table excludes it. Counting it would credit the graph with a
  link it never made.
- Explaining hops needs evidence rows, not traversal, so the CLI opens the graph with
  `CreditGraph.open(..., build_edges=False)` — skipping the ~2.5-minute `credit_edges`
  materialization. That mode raises on any traversal call rather than silently returning
  an empty graph.

## Follow-on

`verify_challenge_evidence` (and its Pi mirror `verify_challenge_job.py`) currently
checks only that both hop endpoints hold a playable credit on the evidence release —
**precisely the release-container assumption this ADR removes**, so it would not have
caught this bug. It should be upgraded to assert the invariants above per hop (endpoints
not placeholders; `same_recording` hops share a `track_index`; `release_scope_credit`
hops pair a `release_artist` with a `release_credit` on an album-shaped release; no
justifying credit is a quotation). Those are point queries against a single release, so
they fit a 1GB Pi worker on a bounded, checksummed partition. Critically, that checker
**must not import `credit_edges_sql`** — a mirror of the same SQL would reproduce any
bug in it and prove nothing.
