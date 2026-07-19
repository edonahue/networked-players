# ADR 0037: Hybrid album catalog assembly for the real-data launch

- **Status:** Accepted
- **Date:** 2026-07-19
- **Relates to:** [ADR 0012](0012-real-discogs-api-demo-challenge.md), `data/albums/README.md`,
  `data/contracts/challenge-v2.md`

## Context

`data/albums/README.md` documents a settled convention: `top-albums-v1.json` is a small,
hand-picked, unranked editorial list, and `rank-album-candidates`' proxy-ranked output is
"curation input for a human to review, never committed or auto-merged into `top-albums-v1.json`."

The real-data launch needs a broader album backbone (roughly 60-90 connected albums) than the
91-entry editorial list alone reliably produces once studio-album format gating and
relationship exclusion are applied. The operator's launch brief explicitly calls for "the
existing recognizable editorial album list as a backbone" plus "graph-rich additions
discovered through measured candidate scoring" -- i.e., deliberately extending album selection
beyond hand-picking for this launch, which is exactly the settled direction the README's
"never auto-merged" line protects.

## Decision

Add graph-rich candidates to the **generated, build-time album list fed to
`build-challenge-from-dump`**, never to the committed `data/albums/top-albums-v1.json` source
file itself. Concretely:

1. `rank_album_candidates` (extended, `packages/graph-core/.../analysis.py`) now also resolves
   each candidate to a real `{artist_id, artist_name}` via the main release's release-artist
   credit, and accepts an optional `release_format_policy` so a non-studio-album candidate
   (compilation, bootleg, ...) never surfaces as a candidate at all.
2. A new function `assemble_album_catalog` (same module) combines the editorial backbone
   (always included, always wins on artist-ID collision) with top-scored graph-rich candidates
   up to a `target_count`, deterministic given a fixed snapshot, format-policy version, and
   editorial list -- no randomness, no manual step required to reach the target count.
3. The **combined list is never committed** -- it is exactly as local/regenerable as
   `rank-album-candidates`' own existing output, consumed directly as `--albums` input to
   `build-challenge-from-dump`. `top-albums-v1.json` keeps its documented meaning unchanged: a
   small, hand-picked, unranked editorial list, reviewable independently of graph state.
4. The only thing that becomes public is the final `challenge.v2.json` artifact -- already
   subject to `validate_challenge`'s leak/structure checks and its own provenance block -- not
   an intermediate candidate list.
5. Private-collection influence on candidate ranking (if used) stays entirely local: an
   optional weighting hook may be layered onto candidate scores by a local-only, gitignored
   module, never published, never distinguishable in the output from a purely graph-derived
   score. See `docs/PUBLIC_PRIVATE_BOUNDARY.md`.

## Why not amend `top-albums-v1.json` itself

The README's hand-picked/unranked framing is a real, useful property independent of this
launch: it lets a human audit exactly what was deliberately chosen without re-deriving it from
graph state, and keeps the file stable across snapshot refreshes. Mixing scored candidates into
it would silently erode that property for every future reader of the file. Keeping the
generated combined list separate preserves both: the editorial file stays exactly what it says
it is, and the launch still gets a broader, real, deterministic backbone.

## Consequences

- `data/albums/README.md` gains a note pointing at this ADR and the new `build-album-catalog`
  command, without changing its "never auto-merged into `top-albums-v1.json`" claim -- that
  claim remains true.
- A future monthly refresh regenerates the combined list from scratch (same inputs -> same
  output); it never accumulates drift the way a hand-edited file could.
- Graph-rich additions are exactly as auditable as the editorial list: every album in
  `challenge.v2.json` traces to either an editorial query or a candidate score, both real and
  reproducible, never a black-box ranking.

## Validation

`packages/graph-core/tests/test_analysis.py` covers the extended `rank_album_candidates`
(artist resolution, format-policy filtering) and a new `assemble_album_catalog` test covers:
editorial entries always winning on collision, deterministic ordering, and respecting
`target_count` without padding past what real candidates support.

## Revisit trigger

If a future editor wants graph-rich candidates to become part of the reviewable,
version-controlled editorial history (not just a regenerable build input), that is a real
product decision -- promoting a candidate into `top-albums-v1.json` by hand remains available
and unaffected by this ADR. Revisit if the combined list's size or turnover between snapshots
makes "generated, not committed" hard to reason about in practice.
