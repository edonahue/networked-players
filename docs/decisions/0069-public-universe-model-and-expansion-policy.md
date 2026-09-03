# ADR 0069: Public universe model and expansion policy (graph-expansion Phase 0)

- **Status:** Accepted (domain model and eligibility foundation); catalog growth itself is
  deferred to Phase 2 of `docs/GRAPH_EXPANSION_DIRECTION.md`
- **Extends:** [ADR 0038](0038-hybrid-album-catalog-assembly.md) (hybrid catalog assembly),
  [ADR 0043](0043-connection-guesser-corrective-slice.md) (established `catalog_version` as
  the single source of truth every public surface derives its album set from),
  [ADR 0058](0058-album-credit-membership-and-evidence-registry.md)/
  [ADR 0059](0059-recommended-route-selection.md) (evidence registry, caveat tiers),
  [ADR 0065](0065-phase7-bucket-a-personal-lane-allocation.md) (personal-seed lane),
  [ADR 0068](0068-performer-only-public-graph.md) (performer-only graph) without modifying
  any of them
- **Supersedes:** the positional-lane convention `catalog_audit.py::_selection_source`
  used before this ADR (reconstructing provenance by array index against
  `pre_resolved_buckets`), for any catalog that adopts schema v2

## Context

Plan Mode (2026-09-02, `docs/GRAPH_EXPANSION_DIRECTION.md`) asked for a path from 179
curated albums to a substantially larger, evidence-first performer network. Slice 0-A
(PR #213, merged) fixed the challenge pair-order bug that was the highest-value,
lowest-risk change. This ADR is Slice 0-B: the domain-model foundation the actual catalog
growth (Phase 2) needs before it starts, plus a real master-level eligibility gate that
fixes a measured false negative.

Two assumptions from the plan turned out to already be true of the current code, found
during implementation rather than assumed from the plan text:

1. **The replication-generation blocker the plan describes is already fixed.**
   `infra/ansible/playbooks/replicate-dataset-x86.yml`'s `allowed_dataset_pattern` regex
   already accepts `discogs-onehop-v4` (and any `-vN`/`-run<N>`/`-full` suffix) — a prior
   PR's own inline comment narrates fixing exactly the bug this ADR's source plan flagged.
   No `platform.models.DatasetRef` class exists or is needed.
2. **The evidence registry already links a release to its catalog album.** The plan asked
   for a new `catalog_album_id` field per registry entry; `evidence_release_registry.py`
   already builds `relation_to_catalog_album_ids` (a parallel array, same join, different
   name) since ADR 0058. No rename — the existing field is functionally identical and
   renaming it for naming-consistency alone would be pure churn.

Neither needed code changes here; both are recorded so a future reader doesn't
re-investigate a closed question.

## Decision

### 1. Featured vs. graph record is per-album metadata, not a new entity

`catalog_schema_version: 2` (optional; absent means today's v1 shape, unchanged) adds three
per-album fields:

- `selection_source` — an enum: `editorial` (the `top-albums-v1.json` backbone **or** a
  personal-Discogs-collection pick; both are publicly just "editorial" — see the privacy
  decision below), `already_published` (preserved from an earlier round),
  `graph_rich`/`coverage_gap` (algorithmic picks), or `generic_candidate` (unlabeled
  proxy-ranking shortlist).
- `featured` — a bool, resolved at catalog-build time from `data/albums/featured-v1.json`'s
  `master_id` pins. `true` is an intentionally selected, prominently placed album (may carry
  a one-line blurb); `false` is a "graph record" — an eligible, fully data-forward album
  that was never hand-featured. The distinction is presentation, never eligibility, quality,
  or visibility: every graph record gets the identical album page template, roster,
  1-hop neighborhood, and evidence sections a featured album gets.
- `expansion_round` — the round that added this album (`0` for the original 179). **Known
  limitation, not yet exercised:** a single catalog-build call applies one `expansion_round`
  to every album it resolves, including `already_published`-lane entries carried forward
  from an earlier round. The first real multi-round build (Phase 2) must carry each
  preserved album's original round as data on that lane's input, not rely on this
  parameter's default. No round beyond 0 exists yet, so this is documented, not fixed
  speculatively.

A sibling top-level `catalog_presentation_version` (hash of `id:featured:selection_source`)
lets a presentation-only consumer (apps/web, the inclusion audit) prove what it read,
**without ever touching `catalog_version`'s identity hash** (`artist_id:main_release_id:
master_id:year`, unchanged since ADR 0043). This is the load-bearing design constraint: a
`featured` flip or a selection-source correction must never cascade the 11 other artifact
groups that regenerate on a `catalog_version` change (contributor index, evidence registry,
pathfinding graph, every game). Verified structurally — the identity formula was never
touched, only a new sibling function added.

v2 is opt-in at the builder (`assemble_album_catalog`'s new `featured_master_ids` parameter
gates whether any v2 field is emitted at all) and additive at the two validators
(`analysis.validate_album_catalog`, `contracts.public_album_catalog_failures`, kept in
byte-for-byte agreement the same way `_catalog_version` already was). **The real committed
`albums.v1.json` stays v1-shaped as of this ADR** — the code path is landed and tested, but
the artifact itself regenerates to v2 shape in Phase 1's `graph.v4` PR, per the plan's own
phasing (a schema capability landing ahead of the artifact that uses it, so Phase 1 isn't
also debugging a brand-new catalog shape at the same time as a brand-new graph encoding).

`data/albums/featured-v1.json` (committed, real data) pins all 179 current `master_id`s as
featured — they were hand-selected, so this is accurate today, not a placeholder. Entries
carry an optional `blurb` (null is the normal case; editorial copy is sparse by design,
never a prerequisite for publication).

### 2. The public record never says "personal_editorial"

The owner's decision (recorded in the graph-expansion plan): roughly two-thirds of Round 1's
new albums may come from the personal Discogs collection, via the existing private-seed
import and the public editorial-seed contract. **Whatever the source, the public label is
`editorial`, never `personal_editorial` or any phrase implying a personal collection.**

Two places carried the old internal name and are fixed here:

- `catalog_audit.py::build_album_catalog_audit`'s `selection_source` column now normalizes
  both the legacy positional-bucket-label fallback AND (defensively) a v2 album's own field,
  via one alias map (`personal_editorial` → `editorial`). The committed
  `docs/data/studio-album-catalog-inclusion-audit-v1.json` still literally reads
  `personal_editorial` in its 13 Bucket-A rows until its next real regeneration (which needs
  the masters dataset on the coordination host — not available in this implementation
  session); `docs/STUDIO_ALBUM_CATALOG_AUDIT.md` documents this explicitly rather than
  implying the fix is already reflected in the committed JSON.
- `assemble_album_catalog`'s internal Bucket A lane name (`"personal_editorial"`, used only
  as the `pre_resolved_buckets[].label` key) is deliberately left unchanged — it is
  build-internal provenance metadata with its own existing test coverage, never itself
  rendered publicly (only the audit's derived `selection_source` column is). Renaming it
  would be pure churn across ~15 existing tests for no reader-facing benefit.

A generic-candidate audit row's positional fallback label was also renamed
`graph_candidate` → `generic_candidate` while making this fix, to match the enum above —
the two names had drifted apart with no real committed data affected (`candidate_count_added`
is 0 on the real catalog today, so this fallback has never actually fired in production).

### 3. Master-level eligibility (`master_eligibility.py`)

New `packages/graph-core/.../master_eligibility.py`, composing two already-tested gates
rather than a third:

- `album_policy.master_non_studio_reason` (Discogs editorial genre/style — catches
  soundtracks/stage recordings no format descriptor marks).
- The release-format-policy allow-list (`studio-album-v1`, built upstream in
  `packages/catalog`), passed in as `allowed_release_ids: frozenset[int]` — the same
  frozenset every other graph-core eligibility check already takes as data. **Graph-core
  must never import from `networked_players_catalog`** (`graph.py`'s own module docstring);
  this module respects that boundary by consuming the already-built allow-list, never the
  classifier that produced it.

Fixes a measured false negative: 18 of the 179 catalog albums' `main_release_id` points at a
Reissue/Remastered pressing, which a descriptor-only rule checking only that one pressing
would wrongly reject. `master_studio_eligibility_reason` checks the master's genre/style
plus whether **any** real release under the master (via a new `CreditGraph.
release_ids_for_master`) is format-allowed — not just the one pressing a candidate happens
to cite. `select_master_main_release_id` then prefers the master's own `main_release_id`
when that release is itself allowed, falling back to the earliest-year allowed release under
the master (ties broken by release_id).

**Deliberately per-master, not a bulk DuckDB query with a Python mirror** the way
`album_policy` is — the genuinely new logic (enumerate a master's releases, pick a winner)
is release *selection*, not a predicate worth re-deriving in SQL, and `graph.master`/
`graph.release_ids_for_master` are both already-indexed single-master lookups.
`master_non_studio_reason` keeps its own existing SQL-parity test unchanged; this module
does not need a second one. If a future bulk scoring pass over thousands of Phase 2
candidate masters measures this too slow, that is a real, measured reason to add a batched
form then — not guessed at here (`master_eligibility.py`'s own docstring records this).

### 4. Evidence-release registry kinds: `single`/`ep` caveat flags

`CAVEAT_FLAG_DESCRIPTORS` (contracts, append-only, bit order load-bearing) gains two entries
at the end: `single` (`Single`, `Maxi-Single`) and `ep` (`EP`, `Mini-Album`) — real Discogs
format descriptors (`docs/RELEASE_FORMAT_RESEARCH.md`), measured present in the
20260601 one-hop corpus at Single 117,589 · EP 22,034 · Maxi-Single 8,623 · Mini-Album 1,578
rows. A release tagged with either is real, official, single-artist(s) evidence — just a
narrower release than a full studio album — so it is presentable with an honest kind caveat
rather than silently treated as clean full-album evidence.

`EVIDENCE_CAVEAT_TIERS` (`graph.py`, decides which release is PREFERRED as evidence when a
credited pair shares more than one) gains a fourth, mildest tier
(`"Single", "Maxi-Single", "EP", "Mini-Album"`) after bootleg/container/pressing — a test
(`test_the_ranking_and_the_published_flags_share_one_vocabulary`) already enforced that the
ranking vocabulary and the published-flag vocabulary must be one set, which is why both
sides changed together. **This tier only takes effect on the next pathfinding-graph
rebuild** (Phase 1's `graph.v4` PR) — this ADR's registry regeneration re-scanned the
*existing, unchanged* `graph.v3.json`'s already-evidenced release ids for the new caveat
flags; it did not re-rank which release evidences any pair. Real regenerated
`evidence/release-registry.v1.json`: 10,316 release ids (unchanged count), existing 6 flags'
counts unchanged, 1,015 releases newly flagged `single`, 177 newly flagged `ep`.

**`live_title_signal` (also named in the graph-expansion plan's registry-kinds list) is
deliberately NOT added here.** It is a title-text heuristic
(`catalog_audit.py::_TITLE_SIGNAL_PATTERN`), not a `release_formats.descriptions` value, so
it needs a different code path than the descriptor-matching mechanism `single`/`ep` reused —
forcing it into a mechanism that doesn't fit it would be worse than leaving it for a
dedicated follow-up.

## Consequences

- No catalog growth ships in this ADR. The real committed `albums.v1.json` is byte-identical
  in shape to before it (v1, no v2 fields) — only the builder/validator CODE gained the v2
  capability, proven by unit and integration tests against the real committed file's
  `master_id`s (`test_real_committed_featured_file_marks_every_current_album_featured`).
- The real committed `evidence/release-registry.v1.json` DID regenerate (additive: new
  legend entries, existing entries unaffected) and was re-validated on all 3 Pi workers.
- The real committed `docs/data/studio-album-catalog-inclusion-audit-v1.json` did NOT
  regenerate (masters dataset unavailable in this session) — its 13 Bucket-A rows still
  read `personal_editorial` until the next real audit build. `validate_album_catalog_audit`
  does not check `selection_source` string values, so this does not fail `make check`.
- `apps/web` needs no change: `connectEvidence.ts` already reads `caveat_flag_names`
  dynamically from the registry rather than hardcoding the legend, so the new flags render
  correctly with zero client code changes (verified: `npm run check`, `format:check`, and
  the full Playwright suite all green against the regenerated registry).

## Validation

`make check` (1,489 pytest, ruff, mypy, `validate-public-artifacts`, `validate-album-
catalog-audit` all green); new suites: `test_master_eligibility.py` (7 cases, including the
measured false-negative fixture), `test_graph.py::test_release_ids_for_master_returns_every_
pressing`; catalog v2 tests in `test_analysis.py` (opt-in gate, per-lane selection_source
tagging, `validate_album_catalog` accepting v2) and `test_catalog_contracts.py` (byte-for-
byte cross-check against the graph-core reference, both v1 and v2 shapes); `catalog_audit`
transition assertion (`test_audit_transition_v1_and_v2_agree_on_the_same_real_catalog`)
proving the field-first refactor is a genuine no-op against real v1-shaped data;
`test_evidence_release_preference.py` (a full album beats a Single/EP; a Single/EP beats a
promo pressing, proving the new mildest tier's ordering); `npm run check`/`format:check`/
full Playwright against the regenerated registry.

## Revisit trigger

- If Phase 2's `score-expansion-candidates` measures `master_eligibility`'s per-master
  lookup pattern too slow across the ~5,600–33,000 Pool A/B candidate masters, add a batched
  DuckDB form then, with a real measurement recorded first.
- When `docs/data/studio-album-catalog-inclusion-audit-v1.json` is next regenerated (masters
  dataset available), confirm its `personal_editorial` rows became `editorial` and update
  `docs/STUDIO_ALBUM_CATALOG_AUDIT.md`'s caveat note accordingly.
- `live_title_signal` needs its own design pass (title-regex mechanism, not descriptor
  matching) before it can join the registry's caveat flags.
- The `expansion_round` per-album-uniform limitation must be resolved before any round
  beyond 0 that uses the `already_published` preservation lane.
