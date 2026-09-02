# ADR 0048: Contributor index and pages

- **Status:** Accepted
- **Date:** 2026-08-03
- **Depends on:** [ADR 0047](0047-role-taxonomy-as-a-third-orthogonal-classification-layer.md)

## Context

Albums have been a strong public entity since the real-data launch; contributors
have not. The album page's contributor card carried an explicit comment: "Names
only — deliberately not pages." Phase 2's mission is to make the product feel
like a real music-credit network, which means a visitor encountering a name in
a reveal should be able to open it and see the records, roles, and connections
it carries — the second entry in the record → contributor → other records →
network journey.

Two designs were available: (a) derive contributor pages at build time from
`challenge.v2.json`/`routes/*.json` directly, with no new artifact, or (b)
publish a proper versioned artifact first. (a) would mean every frontend page
re-implements the same aggregation (role classification, degree computation,
evidence lookup) with no independent validator and no stable identity a link
elsewhere in the app could point at confidently. (b) matches the pattern every
other real public surface already follows (`catalog/albums.v1.json`,
`catalog/album-art.v1.json`) — a small, versioned, independently-validated
artifact as the single source of truth for a browsing surface.

## Decision

Add `apps/web/public/data/contributors/index.v1.json`, built by
`build_contributor_index` (`packages/graph-core/.../contributor_index.py`) and
validated by `contributor_index_failures`
(`packages/contracts/.../contributor_index.py`), wired into
`validate-public-artifacts`'s `PUBLIC_ARTIFACT_GROUPS`.

**Built entirely from two already-published artifacts** —
`challenge.v2.json` and `routes/{universe,rounds}.v1.json` — never a fresh
full-corpus DuckDB query. This is the load-bearing design choice: it keeps the
index deterministic and small (549 contributors, 537 KB uncompressed / 54 KB
gzipped, against a 2.9 MB high-water mark already shipped) without adding any
new dependency on the private one-hop working set. A contributor's
`connection_count`/`neighboring_contributor_ids` reflect degree *within these
two published artifacts only* — never the private full corpus, which would
both leak private-seed-adjacent scale information and make the index
non-reproducible from public data alone.

Each contributor record carries: canonical PAN `name` (never ANV — ADR 0043
Finding 1's lesson), `role_categories` (from ADR 0047's taxonomy),
`role_text_examples` (verbatim, capped), `albums` (the endpoint albums of every
path/round this contributor's credits help establish), `decade_activity`,
`connection_count`, `neighboring_contributor_ids` (capped, ranked), and
`evidence` (capped `{release_id, role_text}` pairs).

**Frontend**: `apps/web/src/pages/contributors/[id].astro`, not
`/artists/[id].astro` — "artist" already means something more specific
(Discogs' raw `artist_id`/`ARTIST_RELATIONS_SCHEMA`) elsewhere in this
codebase. Mirrors `albums/[album].astro`'s `getStaticPaths` structure: role
chips, a linked album grid (`AlbumCard.astro`), a neighboring-contributors
grid, and a documented-evidence section reusing `EvidencePanel`/
`buildHopViews` exactly as every other evidence surface does. The album page's
contributor card is now a real link when a contributor page exists, falling
back to a plain (non-linked) card when it doesn't — not every linked artist
in a path clears the index's own inclusion rule (a contributor needs both a
resolvable name and at least one album association), so a dangling link is
never possible.

## Consequences

- **Evidence-not-lineage risk, addressed explicitly**: a "neighboring
  contributors" list could visually read as a social/collaboration graph
  rather than documented co-credits. Page copy states "co-credited on a
  documented release" and "albums whose documented connection involves this
  contributor" — never "worked with," "collaborated with," or "appears on
  this album" (the contract's own validator scans for the first two phrases,
  reusing `catalog.py`'s `_FORBIDDEN_PHRASES` list, duplicated rather than
  imported to keep this contracts module dependency-free of `catalog.py`,
  matching every other module in this package).
- `albums` intentionally does not mean "albums by this contributor" — a
  mastering engineer or session player will show albums they never
  headlined. This is the correct, honest semantic (evidence of a documented
  connection, not an implied discography) but is a real content-model choice
  worth remembering if a future "discography" feature is ever requested —
  that would need new evidence, not a reinterpretation of this field.
- 549 contributors is real, measured output against the current 140-album
  catalog — larger than the 381/263-artist counts in the two source
  artifacts individually, since this index unions every hop participant
  across both, not just each artifact's own `artists[]` reference list.

## Validation

`packages/graph-core/tests/test_contributor_index.py` (builder correctness:
role-text attachment from both source shapes, album-endpoint association,
decade derivation, degree/neighbor computation, determinism, catalog-version
mismatch failing closed) and
`packages/graph-core/tests/test_cli_contributor_index.py` (CLI wiring).
`packages/contracts/tests/test_contributor_index_contracts.py` (contract
validation: version recomputation, catalog cross-check, unknown-category
rejection, dangling-album rejection, dangling-neighbor rejection, duplicate
rejection, forbidden-phrase rejection) and the combined-gate regression test
in `test_public_artifacts_contracts.py`. `apps/web/tests/contributors.spec.ts`
(page renders real data, album-page link resolves, unknown id 404s, sitemap
inclusion).

## Revisit trigger

If a future feature (the exploration graph, Connect Two Records) needs
contributor data beyond what `challenge.v2.json`/`routes/*.json` cover, extend
those two source artifacts first, or add an explicitly versioned `v2` index —
never silently widen `contributor-index-v1` into a private-corpus dependency.

## Addendum (ADR 0058 Slice 8): decade_activity now keys off real evidence-release years

The original `decade_activity` derivation used the `year` field of whichever
connected catalog album anchored a contributor's hop -- not necessarily the
year of the release the contributor is actually credited on. A contributor
whose only documented evidence predates or postdates the anchor album's own
release could be bucketed under the wrong decade.

`build_contributor_index` now takes a third already-published artifact,
`apps/web/public/data/evidence/release-registry.v1.json` (ADR 0058 Slice 3),
and derives each contributor's `decade_activity` from the real years of their
own `evidence[].release_id` entries via the registry's `release_ids`/`years`
parallel arrays -- never the catalog album's year, and never a fresh
full-corpus query (the registry is itself a published, static artifact, same
discipline this ADR's original decision established for the first two source
artifacts). `connection_count`/`neighboring_contributor_ids` are unaffected --
those remain scoped to `challenge.v2.json`/`routes/rounds.v1.json` only, as
originally decided above. `contributor_index_version`'s hash inputs are also
unaffected (`decade_activity` was never one of the hashed identity fields);
the real committed artifact's version changed on this slice's rebuild only
because the underlying `challenge.v2.json`/`routes/*.json` inputs had already
moved since the index was last regenerated, not because of this fix itself.

See `data/contracts/contributor-index-v1.md` (updated) and
`packages/graph-core/tests/test_contributor_index.py`'s
`test_decade_activity_derived_from_the_contributors_own_evidence_release_years`
(a real year-mismatch fixture asserting the fix).

## Addendum: a new companion artifact, `album-hop-distances-v1`

Real production data surfaced the gap this addendum closes: Jamiroquai's
contributor page listed Pink Floyd's *The Dark Side Of The Moon* as a
"documented connection," even though Jamiroquai's own nearest credit is two
hops away (a mastering credit shared with an engineer who separately
mastered an unrelated later Pink Floyd release). This ADR's own Consequences
section already defended the underlying design — `albums` correctly means
"endpoint albums this contributor's credits help establish a path to," not
"albums this contributor appears on" — but the page gave a reader no way to
tell a direct credit from a distant one, so a two-hop chain read as a direct
tie to an artist's best-known record.

The fix keeps the multi-hop attribution (still correct, still valuable) and
makes the distance visible, without touching `contributor-index-v1`'s
existing contract at all. Two review rounds on the PR that introduced this
addendum converged on that constraint from two different directions:

1. **`albums[]` must keep its plain string-id shape.** This artifact is
   runtime-`fetch()`'d, not just build-time imported: `explorerStage.ts`,
   `connect.ts`, and `contributorsDirectory.ts` all fetch this exact
   unhashed `/data/contributors/index.v1.json` URL from already-loaded
   client JS, so an open browser tab from before a deploy could fetch a
   freshly-published index after it. Changing `albums`'s element type from
   a string to an object would silently break that already-loaded old JS.
2. **No new required key on `contributors[]` either**, even an additive
   one. `contributor_index_failures` validates every contributor's key set
   as an *exact* match against a fixed set — the same discipline every
   artifact contract in this package uses. A new required key would reject
   every already-published v1 file under old validator code, and would
   itself be rejected by any external consumer pinned to the documented v1
   key list: a real breaking change hiding behind an unchanged
   `schema_version`, independent of the client-compatibility question above.

Both findings point at the same resolution: hop-distance data belongs in a
**separate, independently versioned artifact**, the same pattern ADR 0058's
evidence-release-registry already established alongside
`contributor-index-v1`. `apps/web/public/data/contributors/
album-hop-distances.v1.json` (`data/contracts/album-hop-distances-v1.md`,
built by `build_album_hop_distances` in the same
`contributor_index.py` module, validated by
`networked_players_contracts.album_hop_distances::album_hop_distances_failures`)
carries `{artist_id, album_id, hop_distance}` triples, sorted by
`(artist_id, hop_distance, album_id)`, cross-validated against both the
canonical catalog and the companion contributor index's own published
`artist_id`s. `contributor-index-v1` itself — schema, key set, version hash —
is completely unchanged by this addendum.

`hop_distance` is the minimum number of documented credit-hops from an
artist's nearest occurrence in any path/round to that endpoint album. `0`
means the artist is directly adjacent to that album's representative artist
(the common case); any value greater than zero — including `1` — means a
real but more distant documented chain, not a direct credit on that album's
own release (a second review finding: an earlier draft only flagged
`hop_distance > 1`, leaving `1`-hop connections rendered identically to
direct ones).

`apps/web/src/pages/contributors/[id].astro` joins the two artifacts by
`artist_id` and renders a short "N documented hop(s) away" note for any
entry with `hop_distance > 0`; the section heading no longer implies every
listed album is a direct credit.

See `data/contracts/album-hop-distances-v1.md`,
`packages/graph-core/tests/test_contributor_index.py`'s hop-distance
fixtures, `packages/graph-core/tests/test_cli_album_hop_distances.py`, and
`packages/contracts/tests/test_album_hop_distances_contracts.py` (including
regression tests for two validator robustness gaps caught in the same
review: a non-string `album_id` from malformed JSON must be reported as a
clean contract failure, never crash the validator via an unguarded
set/dict operation, and a repeated `(artist_id, album_id)` pair must be
rejected even when the sort check alone would pass).

## Addendum: a second companion artifact, `background-only-profiles-v1` (RETIRED by ADR 0068)

**Status: retired 2026-09-02.** This addendum described
`apps/web/public/data/contributors/background-only-profiles.v1.json`, a
companion artifact listing every contributor whose ENTIRE observed role
vocabulary was background-engineering (Mastered By / Recorded By / Mixed
By) or non-substantive, used to de-emphasize ("mute") their non-direct
connections on the contributor and album detail pages. It existed because
`credit_edges_sql` could form a public graph edge from a purely technical
credit, so a mastering-only tie could legitimately appear as a
"connection" that deserved visual de-emphasis rather than removal.

ADR 0068 removed that possibility at the source: a `track_credit`/
`release_credit` row must now pass `is_performer_role` before it can form
an edge at all, so a background-only pair can no longer be a connection
in the first place. Verified fail-closed against the regenerated
artifacts before deletion: **0 of 891** contributor pairs in
`challenge.v3.json` + `routes/rounds.v1.json` classify as background-only,
and **0** contributors in the regenerated `contributors/index.v1.json`
have an entirely background-only role vocabulary. With nothing left to
flag, the artifact, its builder (`build_background_only_profiles`),
contract (`background_only_profiles_failures`), CLI commands, registration
entries, the `is_background_engineering_role` /
`is_background_only_role_profile` predicates and their TS mirrors, and the
`.album-card--muted` / `.contributor-card--muted` styling were all
removed rather than kept as a dormant safety net — this repo's convention
is to delete an approach once it is genuinely unreachable.

The underlying evidence is untouched: a mastering, mixing, or recording
credit is still fully published in `album-credit-membership.v1.json` and
still rendered on album pages as an additional documented credit. Only
its ability to form a traversable public edge (and therefore its need for
muting) is gone.
