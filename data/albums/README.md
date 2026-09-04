# Album selection

`top-albums-v1.json` is a committed, editorial list of `{artist, title}` queries used to
seed the album-centered challenge artifact (`data/contracts/challenge-v2.md`). It is:

- **Assembled from general public knowledge**, not copied from any single publication's
  ranked list. The `source_note` field in the JSON states this explicitly.
- **Deliberately unranked.** Entries are ordered alphabetically by artist, then title --
  there is no popularity or quality ordering implied by position in the file.
- **A query, not a fact.** Each `{artist, title}` pair is matched against a real parsed
  snapshot at build time (`networked_players_graph_core.challenge.match_albums`); a
  snapshot that lacks a matching release reports the entry as missed rather than
  fabricating a match. Matching happens by exact (case-insensitive) title plus a
  release-artist-scope playable credit on that release, preferring the master's main
  release.

## Medium-term curation mechanism

Hand-picking is the short-term approach. The medium-term mechanism (once a full parsed
snapshot is available) is a **proxy-ranking query** --
`networked_players_graph_core.analysis.rank_album_candidates` -- that scores each
`master_id` by release-variant count times total credit-row count. High-variant,
high-credit masters tend to be albums with real cultural footprint (many pressings,
many session credits), which is a reasonable, measurable proxy for "worth including"
without asserting a single ranked list is authoritative.

The CLI's `rank-album-candidates` command writes its output to a **git-ignored,
local-only shortlist** (`local/analysis/album-candidates-<snapshot>.json`) -- it is
curation input for a human to review, never committed or auto-merged into
`top-albums-v1.json`.

## Hybrid catalog assembly for a real-data launch

[ADR 0038](../../docs/decisions/0038-hybrid-album-catalog-assembly.md) adds a second,
narrower way to use `rank-album-candidates`' output: the CLI's `build-album-catalog`
command combines this file's editorial entries with a `rank-album-candidates` shortlist
(format-policy-filtered, resolved to real `{artist, title}` pairs) into a **generated,
also-never-committed** combined album list, deterministic given a fixed snapshot and
target count. That combined list is consumed directly as `--albums` input to
`build-challenge-from-dump` -- it is a bigger, better *build input*, not a change to this
file. `top-albums-v1.json` keeps exactly the meaning documented above: hand-picked,
unranked, reviewable on its own.

## Studio-album correctness inputs (masters + exclusions)

Two inputs keep the generated catalog to real studio albums with original years, both
fail-closed and both threaded through `build-album-catalog` /
`build-challenge-from-dump` / `build-rounds-from-dump`:

- `--masters-root` (a parsed masters snapshot) supplies each album's **original release
  year** (not a reissue edition date) and Discogs' editorial **genre/style**, which
  `graph-core`'s `album_policy` uses to fail-closed exclude soundtracks and stage/screen
  recordings that release-format descriptors miss.
- `studio-album-master-exclusions-v1.json` (this directory) is a small, committed,
  human-reviewed master-ID deny-list — the residual backstop for non-studio masters (live
  albums) that carry *no* structured signal at all. Each entry records why. Same posture
  as `placeholder_artists.json` and the artist-family exclusions; see
  `docs/RELEASE_FORMAT_RESEARCH.md` for the evidence and ADR 0035/0036 for the precedent.

## Adding an album

Add a `{"artist": "...", "title": "..."}` entry to the `albums` array, keeping
alphabetical order by artist then title. Titles and artist names should match how
Discogs credits the release (exact string match at build time, case-insensitive).

## Expansion round policy (graph-expansion Phase 2)

`expansion-policy-v1.json` is the committed, public record of each round's quotas and
thresholds -- roster band, `overlap_existing` minimum for the two automatic lanes
(graph-value, coverage) and the relaxed thresholds collection-sourced editorial picks
score under, and the per-round lane quota (e.g. Round 1's 20 editorial / 6 graph-value /
4 coverage, per the owner's 2026-09-02 instruction that roughly 2/3 of new albums come
from the private collection). The policy is public; which real candidates fill it each
round is a private, per-round editorial decision, never recorded in this file.

For Round 1 specifically, no new lane-assembly code consumes this file automatically --
`build-public-album-catalog` is fed directly through its existing
`--graph-rich-selection`/`--coverage-gap-candidates`/`--personal-seed` inputs (plan
section 5.3), with this policy's quotas enforced by the human review pass, not a program.
A later round may add automated quota enforcement if reviewing three separate input files
by hand proves clumsy at scale -- not built speculatively ahead of that need.

`networked_players_graph_core.score_expansion_candidates` (plan section 5.2) is the tool
that scores real candidates against this policy's thresholds (`roster_size`,
`overlap_existing`, `bridge_span`, `coverage_delta`, `eligibility`, plus
`marginal_new_edges` from the separate `select-graph-rich-candidates` tool) -- its output
is round-scoped, private, and lives under `local/analysis/expansion/round-<n>/`, never
committed.
