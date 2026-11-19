# Catalog expansion pipeline (Phase 2)

The operator runbook for a graph-expansion Phase 2 round (`docs/GRAPH_EXPANSION_DIRECTION.md`,
plan §5–§9): growing the catalog from 179 toward ~500 albums in rounds of roughly 25–100. This
doc starts with the one piece of round mechanics settled so far — which host runs what — and
grows into a full method-plus-round-log doc as later Phase 2 slices land (plan §13 names this
file for that eventual scope; it is deliberately narrow today rather than describing steps that
don't exist yet).

**The rebuild cascade is executable.** `networked-players-catalog round <plan|run|verify>`
(ADR 0072 section 3) sequences every builder, with the order and preconditions the Round 1
incidents showed were needed; see "The runner" below. No real round has been run through it yet.

**Round 1 has run** (2026-09-04 to 2026-09-07, published in PR #246): 179 → 217 albums. The
"Round log" section below carries both the reusable runbook and Round 1's own dated entry.

## Host assignment (plan §17, Slice 2-0)

Every round adds new seed release ids and needs `expand-one-hop` re-run against the full parsed
Discogs snapshot before the rest of that round's cascade can build (plan §5.4). Investigated
directly (real code, real live cluster) before deciding anything, per this whole plan's own
"measure, then decide" discipline — see plan §17 for the full investigation. Two real findings
drove the decision:

- `expand-one-hop` is a two-pass DuckDB scan with a hard synchronization barrier between the
  passes (pass 2 needs the *complete* frontier from pass 1) — genuinely partitionable across two
  hosts in principle, but nothing in `onehop.py` supports that today, and building it means real
  new code (a partition mode, a frontier-exchange round-trip, a merge-and-resort step) for a job
  whose wall-clock cost had never even been measured.
- `zimaworker1`'s real, live-checked disk state (checked via SSH, not a stale doc): free space is
  tight (single-digit GB free on a shared eMMC), and its only Discogs-related cache is the much
  smaller one-hop-scale corpus — the full parsed snapshot `expand-one-hop` needs is not present
  and replicating it there would violate the established minimum-free-space floor (ADR 0057).

**Decision: job-level split, not a true intra-job partition/merge.**

| Host | Runs |
|---|---|
| Coordination host | `expand-one-hop` (already holds the full parsed dataset — no new replication, no new disk risk) |
| `zimaworker1` | Whichever of that round's genuinely concurrent jobs it already fits: the pair-sweep, candidate-extraction, and Leiden/prominence-adjacent jobs (plan §9), plus `score-expansion-candidates` (real and built, `networked-players-catalog score-expansion-candidates`) |

Both run *while* the coordination host is mid-`expand-one-hop`, not sequentially after it — real
wall-clock overlap within one round, using both boards, with zero new disk pressure and no new
distributed-dispatch primitive. See plan §17 for why a true two-host partition/merge was
considered and explicitly deferred (gated on a real measured bottleneck *and* real disk headroom
for the input replication — neither true today — and weighed against ADR 0032→0034's precedent
of this exact distributed-job shape being tried once and abandoned for one capable host).

## `expand-one-hop`: timing and progress

`expand-one-hop`'s wall-clock cost had never been recorded anywhere, even privately, before this
slice. It now:

- Prints coarse per-pass progress to stderr (start/end of each of the two DuckDB scans, with
  elapsed time and the frontier/retention count) unless `--quiet` is passed. Stderr only —
  `--output`/the printed JSON summary on stdout are unaffected.
- Records real elapsed time for each pass in its own manifest, under `expansion.
  pass1_frontier_elapsed_seconds` / `expansion.pass2_retention_elapsed_seconds`. The manifest
  lives under the git-ignored `local/` tree (never committed or published), so a real number
  there carries none of ADR 0018's public-artifact restriction — the same private-timing
  discipline `local/benchmarks/` already applies elsewhere in this repo.

Record the first real run's numbers here once Round 1 actually executes `expand-one-hop` — that
baseline is the number any future true-host-split decision must be gated on (plan §17's own
revisit trigger).

## Other long-running builders: the same progress-logging fix

`build-challenge-from-dump`, `build-pathfinding-graph`, and `build-album-credit-membership` all
gained the same stderr-only, `--quiet`-suppressible progress logging (plan §18/slice 2-0b) —
directly motivated by a real, live gap: this slice's own local 500-tier benchmark build of
`build-challenge-from-dump` sat silent for 30+ minutes with zero way to tell whether it was
progressing or stuck. `build-challenge-from-dump` additionally reports a naive ETA from the
observed rate so far, once its own progress line starts firing (candidate-pair counts of 50 or
more; smaller runs finish before a progress line would matter).

## Round log

What follows is the real, corrected round runbook — every required argument, the corrected
builder order, and the manual/human-judgment steps — written down so a future round (or a
future session with no memory of this one) can execute it without re-deriving it from the
CLI source. It replaces reliance on any one planning session's own memory (plan §20.5 Slice
R1-D). **Round 1's own dated entry is at the end of this section**; each future round appends
one below it.

A round entry records the real command history and any deviation from this runbook. It does
**not** record wall-clock numbers: ADR 0018 keeps every real elapsed time measured on this
machine out of the public repository. Timings go to `local/benchmarks/` (gitignored) and the
entry points at the file rather than reproducing the numbers.

### Real correction this runbook fixes

An earlier pass at this sequence assumed an order that turns out to violate real CLI
dependencies and to skip two required rebuilds entirely (plan §20.1, found by tracing
every builder's actual `required=True` arguments against what `validate-public-artifacts`
cross-checks):

- `build-prominence`, `build-contributor-index`, and `build-search-index` all require an
  artifact that must be built *before* them, not after (`--evidence-release-registry` for
  the first two, `--contributor-index` for the third).
- `build-record-routes` and `build-album-art-registry` were missing from the assumed
  order entirely. `build-record-routes`'s own output (`routes/{universe,rounds}.v1.json`)
  is a required input to both `build-evidence-release-registry --routes-rounds` and
  `build-contributor-index --routes-universe/--routes-rounds`. `build-album-art-registry`
  is required by `build-evidence-release-registry --album-art`, and its own
  `catalog_version` is **hard-checked** by `album_art_failures` — skip this rebuild after
  a catalog expansion and `make check` fails, it does not silently pass.

**Formerly a silent-pass trap (closed by Campaign Atlas F1a):** `record_routes_failures` and
`connection_rounds_failures` used to take no `catalog` argument, so `make check` passed green
with a stale Record Routes or Connection Guesser. `validate-public-artifacts` now cross-checks
both (and the challenge) against the catalog: `provenance.catalog_version` must equal the
catalog's, every album must exist in the catalog with the same title and artist (a subset is
fine; the pools apply their own eligibility), and the evidence release registry must contain
every release id the challenge, routes rounds and graph cite. A stale pool now fails
`make check` with a "rebuild it" message. The frozen daily generations and the daily
manifest are deliberately exempt (ADR 0041, ADR 0066). Rebuilding them every round is still
the operator's job; CI now enforces it.

**Declared lineage (Campaign Atlas F1b; `data/contracts/artifact-lineage-v1.md`).** Version
equality with the catalog does not see a *challenge-only* rebuild: the evidence registry,
contributor index and hop distances stay green although their input changed. Builders now stamp
`provenance.inputs` (`{artifact: content_version}`), the challenge gains
`provenance.challenge_version`, and `validate-public-artifacts` fails a live artifact whose
declared input version no longer matches the current upstream artifact, naming both. This only
bites for artifacts rebuilt with this version of the builders: everything committed before it
declares no inputs, passes, and is listed under `lineage.undeclared_inputs` in the command's
JSON output until its next rebuild. Rebuild in the order above and rebuild every downstream
artifact after any upstream one.

### Steps 1–8: candidate discovery through owner review (no publication yet)

These steps produce *proposals*. Nothing here authorises publication: the approved pool does
(ADR 0072 section 2), and the runner publishes exactly the pool. All outputs stay under
`local/` or `data/private/`.

0a. **Theme-seed supply from the FULL corpus (Campaign Atlas SS).** Themes outside the
   current one-hop corpus (e.g. desert rock) cannot be found by the steps below, which read the
   one-hop corpus; supply them first from the full parsed corpus. Write the round's seed spec
   (`data/rounds/round-<n>-seed-spec-v1.json`, contract `data/contracts/round-seed-spec-v1.md`;
   the real Round 2 file is an owner/operator TODO, see `data/rounds/README.md`), validate it
   (`validate-round-seed-spec --spec ...`), then run the runner's `theme-supply` stage
   (`round run --spec ... --only-stage theme-supply`) or the underlying
   `build-theme-candidates` directly. **Release-format coverage:** the usual
   `--release-format-policy` scoring index was built over the one-hop corpus only, so masters
   outside it (desert rock, much fusion) have no releases in it and would wrongly report
   `no_format_allowed_release_under_master`. Pass `--classify-pool-releases`: after the capped
   pool is chosen, ONLY the releases under the pool's masters are classified from the full
   `--dataset` (bounded; the same `classify_formats` rules, never the whole corpus) and the
   result is explicitly unioned with `--release-format-policy` (refused if policy version or
   snapshot differ). The same bounded mode is available standalone:
   `classify-release-formats --master-ids <json list> [--release-ids <json list>]`, then
   `build-release-format-scoring-index`. Output: `<work_dir>/theme-candidates.json`, private and
   git-ignored (the command refuses a committable path). Each row is `rank-album-candidates`
   shaped plus `eligibility` (via `master_eligibility`) and `themes` (which theme, by which
   route: seed master, seed-artist master, or shared performers). Each theme's summary also lists `ineligibility_reasons` and `dropped_seed_masters` (explicit seed masters that did not reach the pool, with a reason) so a seed is never silently lost. Caps and the overlap reservation apply to eligible masters only; rows carry advisory `review_flags` (`live_title`, `compilation_title`) shown in the review packet. The runner's `theme-supply` stage passes `--classify-pool-releases` itself. Check each theme's
   `eligible_count` against its lane quota before going on. Then score with
   `score-expansion-candidates --candidates <that file> --onehop-root <scoring corpus>
   --release-format-policy <the MERGED scoring index>` (`--merged-format-index-output`, which
   `build-theme-candidates` writes and the runner places beside the candidates; the one-hop
   index would make the scorer re-derive out-of-corpus themes as ineligible). The candidates
   file holds SELECTED eligible rows only; considered-but-ineligible rows and the per-theme
   summaries go to `--diagnostics-output`. The
   scorer reads credits from `--onehop-root`, and the theme albums only exist in the full
   corpus. Do not point the scorer at the 12 GB full corpus; build a bounded scoring corpus
   first with `build-scoring-corpus --onehop-root <one-hop> --full-root <FULL corpus>
   --masters-root <masters> --candidates <that file> --output-root local/...` (one-hop corpus
   plus every row of the candidate masters' releases; one batched DuckDB pass per table; atomic;
   manifest records both source manifest digests and the candidates file's sha256). The scorer
   reads only the candidate masters' releases and the credits of their selected main release
   (bridge span reads the pathfinding graph JSON), so no other-release performer credits are
   needed; a parity test pins byte-identical scoring against the full corpus. Rebuild it
   whenever the candidates file changes.
   The scorer drops the `themes` column, so keep the supply file beside the scored one when
   reviewing.
0. **Supply candidates first.** Scorers and re-rankers are consumers, not producers (Round 1
   delivered 6 albums against a target of 30 because no supply stage existed). Run the
   supply commands before anything below, and check the pool sizes against the lane quotas:
   - `build-collection-candidates` (candidates derived from the private release-ID seed;
     the output stays local) and
   - `build-relationship-pool` (performers who already connect to the catalog; local-only
     output).

   Both are documented by `--help`. Themes named in the round spec are labels only; naming a
   theme approves no album (ADR 0072 section 7).

1. **Refresh the private seed** from the real collection export (path confirmed with the
   owner, never fabricated or guessed):
   ```bash
   uv run networked-players-catalog import-seed \
     --input <the real collection-export CSV path> \
     --output data/private/discogs-seed.json
   ```
2. **Rank candidates** against the *current* one-hop corpus (this does not need a widened
   corpus):
   ```bash
   uv run networked-players-catalog rank-album-candidates \
     --dataset local/processed/discogs-onehop-v4/snapshot=20260601 \
     --output local/analysis/expansion/round-<n>/candidates.json \
     --release-format-policy <path-to-release-format-scoring-index.json> \
     --masters-root <masters-root>/snapshot=20260601 \
     --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
     --exclude-published-catalog apps/web/public/data/catalog/albums.v1.json
   ```
   **Size `--limit` generously (measured 2026-09-04).** The ranking scores raw corpus weight,
   which favours artists already in the catalog; at `--limit 200` every in-band coverage
   candidate had `new_performers = 0`. Start at `--limit 1000` and check the
   `new_performers` distribution before treating a lane's picks as final.
3. **Score the shortlist** (`score-expansion-candidates`), resolving
   `data/albums/editorial-seed-v1.json` via `--editorial-seed` and passing
   `measure-coverage-gaps`' output via `--underrepresented-buckets` (it accepts the command's
   dict directly):
   ```bash
   uv run networked-players-catalog score-expansion-candidates \
     --onehop-root local/processed/discogs-onehop-v4/snapshot=20260601 \
     --masters-root <masters-root>/snapshot=20260601 \
     --candidates local/analysis/expansion/round-<n>/candidates.json \
     --pathfinding-graph apps/web/public/data/pathfinding/graph.v4.json \
     --release-format-policy <path-to-release-format-scoring-index.json> \
     --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
     --editorial-seed data/albums/editorial-seed-v1.json \
     --underrepresented-buckets local/analysis/expansion/round-<n>/coverage-gaps.json \
     --output local/analysis/expansion/round-<n>/scored-candidates.json
   ```
   (`local-only-output` is enforced by the command.)
4. **Select the graph-value lane** (`select-graph-rich-candidates`; merged with the scorer's
   output by `master_id`). `--finalists` takes `rank-album-candidates`' own raw output (a flat
   list), not the scorer's dict. Expect fewer picks than `--count`: the greedy selection stops
   when nothing adds marginal value, and that is correct.
   ```bash
   uv run networked-players-catalog select-graph-rich-candidates \
     --dataset local/processed/discogs-onehop-v4/snapshot=20260601 \
     --baseline-catalog apps/web/public/data/catalog/albums.v1.json \
     --additional-baseline data/albums/editorial-seed-v1.json \
     --finalists local/analysis/expansion/round-<n>/candidates.json \
     --count <quota> \
     --output local/analysis/expansion/round-<n>/graph-rich-selection.json
   ```
5. **Measure coverage gaps** (`measure-coverage-gaps`; feeds step 3 and the human step 6).
6. **Resolve coverage gaps into real picks, by hand.** `measure-coverage-gaps` measures; it
   does not select. Write `coverage-gap-candidates.json`
   (`{"snapshot_date": "...", "candidates": [...]}` with a gap rationale per pick) under
   `local/analysis/expansion/round-<n>/`.
7. **Build the review packet** (`build-expansion-review-packet`) combining the three lanes.
   Check `already_published_count` first: `editorial-seed-v1.json` is cumulative, and a packet
   whose entries are nearly all already published means the editorial lane is exhausted.
8. **Owner review and picks.** The non-automatable decision point. Nothing below happens
   until it is done.

### Steps 9–11: before the runner

9. **Approve into the pool.** Add the owner-approved albums to
   `data/albums/approved-pool-v1.json` (public `selection_source` labels only; ADR 0072
   section 2). With a pool, the catalog build fails naming any album it would publish outside
   the pool or any pool album it would drop (including one dropped for eligibility), shortlist
   auto-fill is off, and the `--editorial-albums` default fallback does not apply.
10. **Re-widen the one-hop corpus** for the approved albums (runner stage `onehop-rewiden`,
    `round run --spec ... --only-stage onehop-rewiden`). It runs `build-rewiden-seed` (the
    committed editorial seed carried forward plus one entry per approved-pool master, resolved
    from the full corpus; it fails, writing nothing, if an approved master cannot be seeded)
    and then `expand-one-hop --seed <private seed> --additional-seed <that file> --overwrite`
    over the full corpus into `inputs.onehop_root`'s parent. `onehop_root` must be named
    `snapshot=<full corpus snapshot date>`; `expand-one-hop` stages and swaps, so a failure
    leaves the old corpus intact. Afterwards refresh anything that read the old root (relationship
    pool, fleet replicas). Coordination host only; never replicate the full snapshot to
    `zimaworker1` (plan §17, ADR 0057 disk floor).
11. **Write the round spec** (`data/albums/rounds/round-<n>.json`, contract
    `data/contracts/round-spec-v1.md`; synthetic template:
    `data/albums/rounds/example-synthetic-round.json`). Every policy input is stated
    explicitly, as a path or `null` plus a reason. After the catalog build, audit it
    (`build-album-catalog-audit` to `docs/data/studio-album-catalog-inclusion-audit-v1.json`,
    then the manual pass in `docs/STUDIO_ALBUM_CATALOG_AUDIT.md`).

### The runner: steps 12–13 are now `networked-players-catalog round`

The hand-run cascade is replaced by the runner (`packages/catalog/src/networked_players_catalog/round_runner.py`,
ADR 0072 section 3). Export the published artifacts to a separate directory first, because the
runner needs an immutable baseline for carry-forward, inherited parameters and the continuity
check, and refuses to run when the baseline and the output directory are the same:

```bash
mkdir -p local/rounds/round-<n>/previous
git archive HEAD apps/web/public/data | tar -x -C local/rounds/round-<n>/previous --strip-components=3
# spec paths.previous_artifacts_dir = local/rounds/round-<n>/previous/data
# spec paths.output_dir = apps/web/public/data (must be a directory named "data")

uv run networked-players-catalog round plan   --spec data/albums/rounds/round-<n>.json
uv run networked-players-catalog round run    --spec data/albums/rounds/round-<n>.json
uv run networked-players-catalog round verify --spec data/albums/rounds/round-<n>.json
# restart after a failure, naming the stage the run reported:
uv run networked-players-catalog round run --spec ... --from-stage <stage>
```

`theme-supply` and `onehop-rewiden` are opt-in stages: the default `plan`/`run` covers the
publish sequence only, because both straddle the human review steps (supply before scoring and
review, re-widen after the pool is approved). Name them with `--only-stage`, `--from-stage` or
`--to-stage`. `--from-stage theme-supply` is refused unless the range ends at it, because supply is followed by scoring, owner review and approval, which the runner does not perform. `--from-stage onehop-rewiden` is allowed: it runs after the pool is approved. Their inputs (`round_seed_spec`, `full_corpus_root`, `private_seed`,
`editorial_seed`) are stated in every spec and enforced only when the stage is selected;
there are no defaults for any of them.

`--today` defaults to the real UTC date; pass it explicitly to reproduce a plan. The runner
writes artifacts to the spec's `output_dir` (`apps/web/public/data` in a real round),
`stage-results.json` and `report.md` to `work_dir`. Stage progress goes to stderr; no elapsed
time or memory figure is ever printed or recorded (ADR 0018).

| # | Stage | Command (existing builder) | Notes |
| --- | --- | --- | --- |
| opt-in | `theme-supply` | `build-theme-candidates` | step 0a; stage 1 in `STAGES` but outside the default range; private output under `work_dir` |
| opt-in | `onehop-rewiden` | `build-rewiden-seed` + `expand-one-hop` | step 10; follows the approved pool, precedes `catalog`; outside the default range |
| 1 | `prepare-output` | internal | take the daily-manifest baseline and frozen generations from the previous dir when the output lacks them |
| 2 | `catalog` | `build-public-album-catalog` | always `--approved-pool`, `--already-published-catalog`, `--expansion-round`, `--candidates`; explicit lanes from the spec |
| 3 | `album-credit-membership` | `build-album-credit-membership` | |
| 4 | `pathfinding-graph` | `build-pathfinding-graph` | |
| 5 | `challenge` | `build-challenge-from-dump` | always `--albums <new catalog>`, `--carry-forward-challenge <previous>` and `--verify-hops-against-graph <this round's graph>` (G1b) |
| 6 | `record-routes` | `build-record-routes` | always `--previous-routes-universe`; targets inherited unless the spec states them |
| 7 | `freeze-daily-generation` | `freeze-connection-daily-manifest-generation` | freezes the generation pointing at the live rounds file; a no-op when none does |
| 8 | `connection-rounds` | `build-connection-rounds` | refused while any generation points at the live file; always `--previous-connection-universe` |
| 9 | `album-art-registry` | `build-album-art-registry` | needs `DISCOGS_TOKEN` and the private cache; the one stage a test replaces |
| 10 | `evidence-release-registry` | `build-evidence-release-registry` | |
| 11 | `prominence` | `build-prominence` | |
| 12 | `contributor-index` | `build-contributor-index` | |
| 13 | `search-index` | `build-search-index` | |
| 14 | `album-hop-distances` | `build-album-hop-distances` | |
| 15 | `daily-manifest-migrate` | `migrate-connection-daily-manifest-generation` | cutover = planned merge date + lead; never cached or skipped |
| 16 | `format` | Prettier | only files not matched by `apps/web/.prettierignore`; fails if Node or Prettier is missing |
| 17 | `verify` | `validate-public-artifacts`, `check-contributor-continuity`, daily-manifest checks | writes `report.md`; `round verify` runs it alone |

**Hard preconditions** (`round plan` evaluates all of them and exits non-zero; `round run`
refuses to start, and re-checks each stage's guard immediately before executing it):

1. Every policy input is present in the spec, as a path or `null` plus a reason. A `null` for
   an input a builder requires fails planning naming the builder.
2. Freeze guard: `connection-rounds` refuses while any daily-manifest generation's
   `rounds_url` is the live rounds file; run `freeze-daily-generation` first.
3. Calendar: the cutover is after the planned merge date, at least two days
   (`_MIN_CUTOVER_LEAD_DAYS`) after both `generated_at` and `--today`, and the schedule stays
   contiguous.
4. The carry-forward challenge, previous Routes universe, previous Guesser universe and
   previous catalog exist; no build parameter would resolve to a code default.
5. `format` honours `apps/web/.prettierignore`.

A round PR also runs the CI-safe pure check against the committed manifest:
`uv run networked-players-catalog round check-cutover --manifest apps/web/public/data/game/daily-manifest.v1.json --today <date>`
(fails when the newest generation's cutover date is not after `--today`). It is not part of
`validate-public-artifacts` because a long-merged round legitimately has its cutover in the
past, and it is not wired into any workflow.

After `round verify` passes: `make check`, read `report.md`, record the real
`removed`/`added` contributor counts in the round entry (Round 1 was 530 → 639, 76 removed,
185 added, **0 endpoints lost**), then Prettier-format nothing by hand.

### Rollback (ADR 0072 section 4)

Rollback of a round is **not** a plain revert. Never revert the daily manifest or the
generation files past a cutover date that has already passed: that rewrites dates players have
already seen (ADR 0041/0066). Revert the round's other artifacts, keep the new generation
frozen in place (freeze it with `freeze-connection-daily-manifest-generation` if it still
points at the live file), and schedule forward with `extend-connection-daily-manifest-v2` or a
new generation whose cutover is still in the future. Before the cutover has passed, a full
revert of the round PR is safe.

### Challenge edge scope (campaign Atlas G1b)

`build-challenge-from-dump` searches only edges with at least one **seed** (catalog primary
artist) endpoint -- the same ADR 0050 rule `build-pathfinding-graph` applies, defined once as
`graph.edge_in_seed_scope` / `seed_scope_sql` and used by both builders
(`GRAPH_POLICY_VERSION` 2; challenge provenance records `build_parameters.path_edge_scope:
"seed_touching"`). A pair whose only routes cross an edge between two non-seed artists is
re-found through a seed-touching alternative or dropped. Carried-forward pairs are always
re-searched, never kept verbatim; the build report prints `carried_pairs_*` and a
`carry_forward_scope` audit (previous paths with an out-of-scope hop, re-found vs dropped).

The check "every published hop is an edge of graph.v4" is available as
`check-challenge-hops-in-graph` and `build-challenge-from-dump --verify-hops-against-graph`.
The round runner enables it in the `challenge` stage and in `verify` for every new round. It
is **not** a `validate-public-artifacts` default yet: the committed challenge.v3 (built under
policy 1) has 119 hops with no graph edge and would fail. **It becomes mandatory with the
Round 2 rebuild**, which regenerates the challenge under policy 2.

Limits of the check and of the scope rule:

- The hop check confirms **adjacency only** (the artist pair is an edge of the graph). It does
  not confirm that the evidence release the challenge cites for a hop is the release the graph
  stores for that edge; aligning that is G1a (one evidence-release selection policy).
- The frontier cap (`max_frontier_expansion`) still counts a node's **full** degree; only
  expansion follows scoped edges, so an inherited cap keeps the meaning it was chosen under.
- Seeds come from the catalog (`graph.catalog_seed_artist_ids`, the graph builder's own source)
  on the catalog-resolved path, so format/studio-exclusion filters on matched albums cannot
  shrink them. A hand-written `{artist,title}` list has no catalog: seeds are then the matched
  albums' artists and the report says `seed_artist_source: "matched_albums"`. The report also
  carries `seed_artists_without_matched_album`, and the carry-forward audit reports
  `pairs_refound_at_different_length`.

### What the runner does not do

- **Album art needs the operator's API cache.** The stage is the existing
  `build-album-art-registry`; it needs `DISCOGS_TOKEN` and the private cache. Only tests
  replace it.
- **Nothing runs in CI.** It is operator-run and is wired into neither a workflow nor
  `make check`; only `round check-cutover` is CI-suitable, and it is not wired in.
- **No real round has been run through it yet.** It is exercised end to end only over a
  synthetic corpus (`packages/catalog/tests/test_round_runner.py`). Its first real use is
  Round 2.
- No stage cache (ADR 0072 section 3), scoring and owner approval stay manual (candidate supply and the post-approval re-widen are the opt-in stages above),
  no fleet validation (steps 14–15 below), no audit.

### Steps 14–15: measure and validate on the fleet

14. **Reprofile**: `node apps/web/scripts/reprofile-site.mjs` against the real new catalog
    size (all three profiles) — compare against the last recorded numbers in
    `local/benchmarks/` (private) per plan §6's budgets.
15. **Pi fleet validation fan-out** on every regenerated artifact; `zimaworker1` runs its
    own concurrent piece of this round's work per the host-assignment table above.

---

## Round entries

### Round 1 — 179 → 217 albums (2026-09-04 → 2026-09-07, PR #246)

**Outcome.** 38 albums added. Catalog schema v2 (`expansion_round` 0 for the original 179,
1 for the 38 new; 211 featured). Every album documented: `albums_missed: 0`, 575 challenge
paths. Contributor index 530 → 639 (185 added, 76 removed), **0 of 173 published path
endpoints lost**. Album art 217/217. Record Routes 350 rounds (150 one-hop + 200 two-hop).
Connection Guesser 343 → 500 rounds, 145 → 190 albums. `graph.v4` gzip grew 1.15× (gate
≤1.6×, absolute ≤2.5 MB). Lane composition as published: 54 editorial, 163 pre-resolved,
0 generic candidates.

**Deviations from the runbook above, and what caused them.** All four were found and fixed
during the round; they are why the runbook now reads as it does.

1. **The candidate-supply stage did not exist.** The first attempt delivered **6 albums
   against a target of 30** and was misdiagnosed as "blocked on owner picks". Root cause: the
   pipeline had a scoring stage and a selection stage and no *supply* stage — all three
   candidate pools this doc specifies were absent, and `rank-album-candidates` (a popularity
   proxy with zero catalog or collection awareness) had been substituted. Fixed by building
   `build-collection-candidates` (PR #243) and `build-relationship-pool` (PR #244).
   Measured: 216 seed releases → 213 masters → 147 eligible, against a 20-slot lane.
2. **`select-graph-rich-candidates` ignored the committed roster band.** 4 of its 6 picks
   violated the 5–30 band and needed a manual pre-filter. Fixed in PR #245; enforcing the band
   *improved* the lane (6/6 slots in band, 36 new performers vs 34).
3. **Three silent-default drifts**, the round's most consequential pattern:
   `--editorial-albums` fell back to `top-albums-v1.json` and added 2 unapproved albums;
   `--expansion-round` stamped all 217 albums as Round 1 additions (fixed with
   `previously_published_rounds`); and `--two-hop-target` used its default 100 instead of the
   published 200, halving two-hop rounds and dropping 94 routes-only contributor pages. The
   systemic fix is build-parameter provenance (PR #248).
4. **Regenerating the Connection Guesser pool broke the daily manifest.** gen-2 still pointed
   at the live `rounds.v1.json`, so all 90 of its scheduled dates — including that day's —
   rendered "could not be verified". Fixed by the ADR 0066 freeze-and-repoint, which is now a
   real tool (`freeze-connection-daily-manifest-generation`) rather than a hand edit, plus a
   gen-3 cutover. `validate-public-artifacts` went from 60 failures to zero.

**Audit.** The manual title-by-title pass over all 38 new albums (per
`docs/STUDIO_ALBUM_CATALOG_AUDIT.md`) flagged exactly one: *The Blues Brothers — Briefcase
Full Of Blues*, a live album carrying 0 `Live` descriptors across 137 pressings. **Owner
decision: kept**, recorded in that document so a later pass does not re-litigate it.

**Timings.** Not reproduced here — ADR 0018. See `local/benchmarks/` (gitignored).

**Follow-ups this round generated:** `extend_connection_daily_manifest` had no schema-v2 form,
so the live manifest could not be extended at all (fixed, PR #247); build-parameter provenance
stamping (PR #248); and the ADR 0048 addendum recording that contributor pages are derived.
