# Catalog expansion pipeline (Phase 2)

The operator runbook for a graph-expansion Phase 2 round (`docs/GRAPH_EXPANSION_DIRECTION.md`,
plan §5–§9): growing the catalog from 179 toward ~500 albums in rounds of roughly 25–100. This
doc starts with the one piece of round mechanics settled so far — which host runs what — and
grows into a full method-plus-round-log doc as later Phase 2 slices land (plan §13 names this
file for that eventual scope; it is deliberately narrow today rather than describing steps that
don't exist yet).

**Not yet run:** Round 1 itself. Every tool it needs is real and built (`score-expansion-candidates`,
plan §5.2, among others — see below); the "Round log" section below documents the real, corrected
command sequence to run it, ready to execute once the owner has completed candidate review.

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

_(No round has run yet.)_ What follows is the real, corrected Round 1 runbook — every
required argument, the corrected builder order, and the manual/human-judgment steps —
written down so a future round (or a future session with no memory of this one) can
execute it without re-deriving it from the CLI source. It replaces reliance on any one
planning session's own memory (plan §20.5 Slice R1-D). Once Round 1 actually runs, a
short dated entry recording the real command history, wall-clock numbers, and any
deviation from this runbook goes below this section.

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

**A real silent-pass trap, worth remembering every round regardless of the fix above:**
`record_routes_failures` and `connection_rounds_failures` (Record Routes and Connection
Guesser) take **no `catalog` argument at all** — `validate-public-artifacts` cannot and
does not cross-check either against `catalog_version`. `make check` will pass green even
if Record Routes or the Connection Guesser are stale relative to a newly-expanded
catalog. Rebuilding them every round is still required; nothing in CI will force it.

### Steps 1–8: candidate discovery through owner review (no publication yet)

1. **Refresh the private seed** from the real collection export (path confirmed with the
   owner, never fabricated or guessed):
   ```bash
   uv run networked-players-catalog import-seed \
     --input <the real collection-export CSV path> \
     --output data/private/discogs-seed.json
   ```
2. **Rank candidates** against the *current* one-hop corpus — this does **not** need the
   widened corpus a new seed might require (confirmed not circular):
   ```bash
   uv run networked-players-catalog rank-album-candidates \
     --dataset local/processed/discogs-onehop-v4/snapshot=20260601 \
     --output local/analysis/expansion/round-1/candidates.json \
     --release-format-policy <path-to-release-format-scoring-index.json> \
     --masters-root <masters-root>/snapshot=20260601 \
     --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
     --exclude-published-catalog apps/web/public/data/catalog/albums.v1.json
   ```
   **Size `--limit` generously — a real, measured finding from the first live run
   (2026-09-04).** `rank-album-candidates` scores by raw corpus weight
   (`variant_count` × `credit_rows`), which strongly favours artists *already* in the
   catalog. At `--limit 200`, the pool was so dominated by already-represented artists
   (more Rolling Stones, Santana, U2, Clapton records) that **every in-band coverage-lane
   candidate scored `new_performers = 0`** — real catalog anchors, but zero performer-network
   growth, which is the entire point of the graph-value and coverage lanes. Whole thin
   genres were also nearly unrepresented in the pool: Reggae had exactly **one** candidate
   in 200, and it was one over the roster cap. Start at `--limit 1000` and check the
   `new_performers` distribution before treating a lane's picks as final.
3. **Score the shortlist**, resolving `data/albums/editorial-seed-v1.json` directly via
   `--editorial-seed` (Slice R1-C — no manual transform step needed), and passing
   `measure-coverage-gaps`' own output (run once, ahead of this step, over the *current*
   catalog) via `--underrepresented-buckets`.

   **Real shape mismatch, hit in the first live run (2026-09-04):**
   `--underrepresented-buckets` wants a *bare JSON list* of
   `{dimension, bucket, count}` objects, but `measure-coverage-gaps` writes a dict
   (`{album_count, catalog_version, composition, masters_resolved, underrepresented}`).
   Passing its output directly fails with `TypeError: string indices must be integers`.
   Extract the list first:
   ```bash
   python3 -c "
   import json
   d = json.load(open('local/analysis/expansion/round-1/coverage-gaps.json'))
   json.dump(d['underrepresented'],
             open('local/analysis/expansion/round-1/underrepresented-buckets.json', 'w'), indent=2)
   "
   ```
   Then:
   ```bash
   uv run networked-players-catalog score-expansion-candidates \
     --onehop-root local/processed/discogs-onehop-v4/snapshot=20260601 \
     --masters-root <masters-root>/snapshot=20260601 \
     --candidates local/analysis/expansion/round-1/candidates.json \
     --pathfinding-graph apps/web/public/data/pathfinding/graph.v4.json \
     --release-format-policy <path-to-release-format-scoring-index.json> \
     --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
     --editorial-seed data/albums/editorial-seed-v1.json \
     --underrepresented-buckets local/analysis/expansion/round-1/underrepresented-buckets.json \
     --output local/analysis/expansion/round-1/scored-candidates.json
   ```
   (`local-only-output` is enforced by the command itself — it refuses to write outside
   `local/`.)
4. **Select the graph-value lane** (a pool-level greedy marginal selection, a materially
   different computation than the per-candidate scorer above — its output is merged with
   the scorer's by `master_id`, not a replacement for it):
   ```bash
   uv run networked-players-catalog select-graph-rich-candidates \
     --dataset local/processed/discogs-onehop-v4/snapshot=20260601 \
     --baseline-catalog apps/web/public/data/catalog/albums.v1.json \
     --additional-baseline data/albums/editorial-seed-v1.json \
     --finalists local/analysis/expansion/round-1/candidates.json \
     --count 6 \
     --output local/analysis/expansion/round-1/graph-rich-selection.json
   ```
   (`--count 6` per `expansion-policy-v1.json`'s Round 1 graph-value quota.)

   **`--finalists` takes `rank-album-candidates`' own raw output** (a flat JSON list whose
   rows carry `artist_id`/`master_id` at the top level), **not** the
   `score-expansion-candidates` output — that one is a dict wrapping its rows under
   `candidates`, and passing it fails with `TypeError: string indices must be integers`
   inside `greedy_marginal_selection`. An earlier draft of this runbook had it wrong; the
   first live run (2026-09-04) caught it.

   **Expect fewer picks than `--count` requests.** The first live run asked for 6 and got
   4: the greedy selection stops when no remaining finalist adds real marginal value.
   That is a correct result, not a bug — do not force it to the quota number (the same
   discipline ADR 0065 applied when Phase 7 targeted +40 and shipped +39 rather than
   manufacture a filler pick).
5. **Measure coverage gaps** against the current catalog (feeds step 3's
   `--underrepresented-buckets`, and separately drives the human resolution in step 6):
   ```bash
   uv run networked-players-catalog measure-coverage-gaps \
     --catalog apps/web/public/data/catalog/albums.v1.json \
     --masters-root <masters-root>/snapshot=20260601 \
     --output local/analysis/expansion/round-1/coverage-gaps.json
   ```
6. **Resolve coverage gaps into real Bucket C album picks — a real human/editorial
   judgment call, not automatable.** `measure-coverage-gaps`'s own module docstring says
   it outright: *"This module measures; it does not select."* Its raw
   `{dimension, bucket, count}` findings are not the shape `build-expansion-review-packet`
   expects for `--coverage-gap-candidates`
   (`{"snapshot_date": "...", "candidates": [...]}` with gap rationale per pick) — turning
   a measured deficit into an actual album requires the same editorial judgment as any
   other pick, just informed by this measurement. Write the result by hand to
   `local/analysis/expansion/round-1/coverage-gap-candidates.json` (per
   `expansion-policy-v1.json`'s Round 1 quota, 4 picks).
7. **Build the review packet** combining all three buckets:
   ```bash
   uv run networked-players-catalog build-expansion-review-packet \
     --catalog apps/web/public/data/catalog/albums.v1.json \
     --personal-seed data/albums/editorial-seed-v1.json \
     --graph-rich-selection local/analysis/expansion/round-1/graph-rich-selection.json \
     --coverage-gap-candidates local/analysis/expansion/round-1/coverage-gap-candidates.json \
     --generated-at <explicit ISO datetime> \
     --output data/private/expansion/round-1/review-packet.json
   ```
   **Check `already_published_count` before reading anything else.**
   `data/albums/editorial-seed-v1.json` is *cumulative* — it keeps every album ever
   resolved into it, including ones a previous round already published. In the first
   live run (2026-09-04) **all 13 of its entries were already in the catalog**, so the
   editorial lane contributed exactly zero new albums, and the round's real growth came
   entirely from the graph-value lane. A packet whose `already_published_count` is close
   to its entry count means the editorial lane is exhausted and needs genuinely new owner
   picks before the round is worth publishing — the seed file being non-empty proves
   nothing.
8. **Owner review and picks — the real, non-automatable decision point this whole
   pipeline exists to inform.** No further step below happens until this is done.

### Steps 9–13: publish the catalog and rebuild every downstream artifact

9. **Build the public catalog**, always passing `--already-published-catalog` explicitly
   (its own help text: omitting it on an expansion "risks silently dropping or replacing
   already-published albums" — re-matching against a possibly-widened corpus does not
   reproduce the same result set even from identical inputs), and now also
   `--featured-albums`/`--expansion-round` to activate catalog schema v2 (Slice R1-B):
   ```bash
   uv run networked-players-catalog build-public-album-catalog \
     --onehop-root local/processed/discogs-onehop-v5/snapshot=20260601 \
     --already-published-catalog apps/web/public/data/catalog/albums.v1.json \
     --personal-seed data/albums/editorial-seed-v1.json \
     --graph-rich-selection local/analysis/expansion/round-1/graph-rich-selection.json \
     --coverage-gap-candidates local/analysis/expansion/round-1/coverage-gap-candidates.json \
     --candidates local/analysis/expansion/round-1/candidates.json \
     --target-count <owner-approved new total> \
     --release-format-policy <path-to-release-format-scoring-index.json> \
     --masters-root <masters-root>/snapshot=20260601 \
     --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
     --featured-albums data/albums/featured-v1.json \
     --expansion-round 1 \
     --output apps/web/public/data/catalog/albums.v1.json
   ```
   (Uses the `discogs-onehop-v5` root from step 11 below if new seed releases were added
   this round; otherwise the still-current `v4` root is fine — order shown here assumes
   the widened corpus already exists, adjust if this round adds no new seed releases.)
10. **Audit the catalog** (automated pass, then the standing manual title pass):
    ```bash
    uv run networked-players-catalog build-album-catalog-audit \
      --catalog apps/web/public/data/catalog/albums.v1.json \
      --onehop-root local/processed/discogs-onehop-v5/snapshot=20260601 \
      --masters-root <masters-root>/snapshot=20260601 \
      --release-format-policy <path-to-release-format-scoring-index.json> \
      --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
      --output docs/data/studio-album-catalog-inclusion-audit-v1.json
    ```
    Then the manual `docs/STUDIO_ALBUM_CATALOG_AUDIT.md` title-by-title pass — the
    pacing variable for round size, per this whole plan's own discipline.
11. **Widen the one-hop corpus** — only if this round's picks introduced release ids the
    current `discogs-onehop-v4` doesn't already contain (a mostly-collection-sourced round
    usually doesn't, since the collection was already the private seed's frontier):
    ```bash
    uv run networked-players-catalog expand-one-hop \
      --dataset <parsed-discogs-snapshot-root>/snapshot=20260601 \
      --output-root local/processed/discogs-onehop-v5 \
      --additional-seed data/albums/editorial-seed-v1.json
    ```
    Runs on the coordination host only (plan §17) — it already holds the full parsed
    dataset; never replicate the full 6.6 GB snapshot to `zimaworker1` to run this there
    (real, live-checked disk-floor blocker, plan §17). `zimaworker1` instead runs
    whichever of this round's genuinely concurrent jobs it already fits — the pair-sweep,
    candidate-extraction, or Leiden/prominence-adjacent work, plus `score-expansion-candidates`
    (step 3 above) — *while* this step runs on the coordination host, not after it.
12. **The full builder cascade, in the corrected order** (every `--generated-at` is an
    explicit ISO datetime, never the wall clock):
    ```bash
    uv run networked-players-catalog build-album-credit-membership \
      --onehop-root local/processed/discogs-onehop-v5/snapshot=20260601 \
      --catalog apps/web/public/data/catalog/albums.v1.json \
      --output apps/web/public/data/albums/credit-membership.v1.json \
      --generated-at <explicit ISO datetime>

    uv run networked-players-catalog build-pathfinding-graph \
      --onehop-root local/processed/discogs-onehop-v5/snapshot=20260601 \
      --catalog apps/web/public/data/catalog/albums.v1.json \
      --album-credit-membership apps/web/public/data/albums/credit-membership.v1.json \
      --output apps/web/public/data/pathfinding/graph.v4.json \
      --generated-at <explicit ISO datetime>

    uv run networked-players-catalog build-challenge-from-dump \
      --onehop-root local/processed/discogs-onehop-v5/snapshot=20260601 \
      --masters-root <masters-root>/snapshot=20260601 \
      --release-format-policy <path-to-release-format-scoring-index.json> \
      --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
      --in-memory-search --max-frontier-expansion 0 \
      --output apps/web/public/data/challenge.v3.json

    uv run networked-players-catalog build-record-routes \
      --onehop-root local/processed/discogs-onehop-v5/snapshot=20260601 \
      --albums apps/web/public/data/catalog/albums.v1.json \
      --release-format-policy <path-to-release-format-scoring-index.json> \
      --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
      --masters-root <masters-root>/snapshot=20260601 \
      --output-universe apps/web/public/data/routes/universe.v1.json \
      --output-rounds apps/web/public/data/routes/rounds.v1.json

    uv run networked-players-catalog build-album-art-registry \
      --catalog apps/web/public/data/catalog/albums.v1.json \
      --output apps/web/public/data/catalog/album-art.v1.json \
      --cache-dir data/private/discogs-api-cache \
      --generated-at <explicit ISO datetime>

    uv run networked-players-catalog build-evidence-release-registry \
      --onehop-root local/processed/discogs-onehop-v5/snapshot=20260601 \
      --challenge apps/web/public/data/challenge.v3.json \
      --routes-rounds apps/web/public/data/routes/rounds.v1.json \
      --pathfinding-graph apps/web/public/data/pathfinding/graph.v4.json \
      --album-art apps/web/public/data/catalog/album-art.v1.json \
      --catalog apps/web/public/data/catalog/albums.v1.json \
      --output apps/web/public/data/evidence/release-registry.v1.json \
      --generated-at <explicit ISO datetime>

    uv run networked-players-catalog build-prominence \
      --pathfinding-graph apps/web/public/data/pathfinding/graph.v4.json \
      --evidence-release-registry apps/web/public/data/evidence/release-registry.v1.json \
      --output apps/web/public/data/pathfinding/prominence.v1.json \
      --generated-at <explicit ISO datetime>

    uv run networked-players-catalog build-contributor-index \
      --challenge apps/web/public/data/challenge.v3.json \
      --routes-universe apps/web/public/data/routes/universe.v1.json \
      --routes-rounds apps/web/public/data/routes/rounds.v1.json \
      --catalog apps/web/public/data/catalog/albums.v1.json \
      --evidence-release-registry apps/web/public/data/evidence/release-registry.v1.json \
      --output apps/web/public/data/contributors/index.v1.json \
      --generated-at <explicit ISO datetime>

    uv run networked-players-catalog build-search-index \
      --catalog apps/web/public/data/catalog/albums.v1.json \
      --contributor-index apps/web/public/data/contributors/index.v1.json \
      --output apps/web/public/data/search/index.v1.json \
      --generated-at <explicit ISO datetime>

    uv run networked-players-catalog build-album-hop-distances \
      --challenge apps/web/public/data/challenge.v3.json \
      --routes-rounds apps/web/public/data/routes/rounds.v1.json \
      --catalog apps/web/public/data/catalog/albums.v1.json \
      --contributor-index apps/web/public/data/contributors/index.v1.json \
      --output apps/web/public/data/contributors/album-hop-distances.v1.json \
      --generated-at <explicit ISO datetime>
    ```
    Each JSON artifact then needs `npx prettier --write <path>` (from `apps/web/`) before
    committing — the builders' own `json.dumps(indent=2)` output is not byte-identical to
    the Prettier formatting `npm run format:check` requires.
13. **`make check`.** Watch for two things it will and will not catch:
    - It **will** hard-fail if `build-album-art-registry` (step 12) was skipped — the
      registry's `catalog_version` is cross-checked against the new catalog.
    - It will **not** catch a stale Record Routes or Connection Guesser (the silent-pass
      trap above) — confirm both were actually rebuilt this round by their own
      `catalog_version` fields, don't rely on `make check` alone.

### Steps 14–15: measure and validate on the fleet

14. **Reprofile**: `node apps/web/scripts/reprofile-site.mjs` against the real new catalog
    size (all three profiles) — compare against the last recorded numbers in
    `local/benchmarks/` (private) per plan §6's budgets.
15. **Pi fleet validation fan-out** on every regenerated artifact; `zimaworker1` runs its
    own concurrent piece of this round's work per the host-assignment table above.
