# Catalog expansion pipeline (Phase 2)

The operator runbook for a graph-expansion Phase 2 round (`docs/GRAPH_EXPANSION_DIRECTION.md`,
plan §5–§9): growing the catalog from 179 toward ~500 albums in rounds of roughly 25–100. This
doc starts with the one piece of round mechanics settled so far — which host runs what — and
grows into a full method-plus-round-log doc as later Phase 2 slices land (plan §13 names this
file for that eventual scope; it is deliberately narrow today rather than describing steps that
don't exist yet).

**Not yet run, so not described below:** the round itself — `score-expansion-candidates` (plan
§5.2) is real and built (see below), but no Round 1 has run yet. This doc will grow a "round
log" section once one has.

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

_(No round has run yet — this section starts once Round 1 does.)_
