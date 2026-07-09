# ADR 0032: Cohort connectivity's fleet-distribution dispatch unit is a chunk of unique seed artists, mirroring `verify_challenge_job.py`

- **Status:** Accepted
- **Date:** 2026-07-09

## Context

A real cohort rehearsal (source `discogs-community-best-albums`, 25 canonical/prolific
artists) exposed two distinct problems this session, fixed in order:

1. `CreditGraph.open()` left `linked_credits` as a lazy `VIEW`; every BFS query re-scanned
   and re-filtered the full credits data from scratch. Materializing it (a plain `TABLE`,
   not `TEMP TABLE` -- DuckDB's temp schema turned out to be cursor-local, breaking the
   cross-cursor sharing this ADR's own design also depends on) took the worst hub artist
   (61,253 credit rows) from "never completes in 120s" to 1.10s standalone.
2. `_bfs_from_seed`'s own frontier-size check and neighbor fetch looped per artist in
   Python instead of batching a whole hop's frontier into one query each (the pattern
   `CreditGraph.find_path` already used). Batching this (new `credit_row_counts`/
   `neighbors_batch` methods) removed the per-call round-trip overhead that dominated a
   hub's hop-2 expansion (14,000+ frontier artists at hop 1 for the worst case).

A first cut at *local* concurrency (`CreditGraph.cursor()`, `score_pairs`'s
`max_workers` -- dispatching different unique cohort artists' own BFS across
`ThreadPoolExecutor` workers on one host) helped modestly but is inherently bounded by
this host's own core count. Real further throughput for this class of work -- and for
`resolve-cohort`/`build-challenge-from-dump`, which now share the same
batch-first/cursor-concurrent pattern -- means spreading independent per-artist work
across the fleet (this master, `zimaworker1`, and three Pi 3B workers), not just this
host's cores.

Two things this session's codebase survey confirmed matter for that:

- **RQ is real, working infrastructure**, but every existing job body is either a
  synthetic benchmark or dataset-free JSON validation, with one exception:
  `infra/ansible/files/verify_challenge_job.py`, a self-contained (stdlib + `duckdb`
  only) Pi job that queries the real one-hop dataset from `CATALOG_DATA_DIR` (ADR 0025).
  It deliberately avoids importing `networked_players_graph_core` because a Pi's lean
  worker venv excludes `lxml`/`pyarrow` -- though `CreditGraph` itself only needs
  `duckdb`, so that specific exclusion doesn't actually block importing it; the
  self-contained-mirror *pattern* (a hand-maintained copy, cross-checked by a test
  against the real implementation) is still worth keeping regardless, since it avoids
  coupling worker venvs to graph-core's own dependency surface as that surface changes.
- **`docs/HARDWARE.md` is explicit**: "Pi jobs must fit comfortably within 1 GB RAM with
  explicit concurrency limits... never graph traversal, scoring, or full-catalog work."
  `verify_challenge_job.py` respects this by only ever running bounded, single-purpose
  queries per job, never open-ended traversal.

## Decision

**Dispatch granularity is a chunk of unique seed artists, not individual neighbor
lookups.** An RQ round-trip per single frontier-artist lookup would very likely cost
more than the batched local query it would replace (RQ enqueue/dequeue latency vs. a
sub-second DuckDB query). This mirrors exactly what `--max-workers` already does
locally -- partition the unique-artist list into chunks, one chunk per worker -- just
moving a chunk's execution onto a remote worker process instead of a local thread.

**A new self-contained job body**, `infra/ansible/files/cohort_seed_bfs_job.py`
(stdlib + `duckdb` only, no `networked_players_graph_core` import, following
`verify_challenge_job.py`'s exact precedent), exposing
`run_seed_bfs_chunk(seed_artist_ids, max_hops, max_frontier_expansion, snapshot_date) ->
dict[str, Any]`. It is a hand-maintained mirror of `_bfs_from_seed` plus the batched
`credit_row_counts`/`neighbors_batch` queries, cross-checked against the real
implementation by `packages/graph-core/tests/test_cohort_seed_bfs_job_body.py` (mirroring
`test_verify_job_body.py`'s `importlib.util.spec_from_file_location` pattern) on the same
synthetic fixture, so the two can't silently drift apart. It reads the dataset from
`CATALOG_DATA_DIR` only (ADR 0025) -- never a network fetch -- so the precondition is the
same as `verify_challenge_job.py`'s: the target worker must already hold a validated
one-hop cache for the snapshot being scored.

**A chunk is still a bounded, timeout-guarded unit, not open-ended traversal**, which is
what keeps this consistent with `docs/HARDWARE.md`'s Pi constraint: the orchestration
(BFS looping across hops for one chunk's seeds) happens inside one RQ job with its own
wall-clock budget, the same shape `verify_challenge_job.py`'s per-hop checks already
are -- it is not a standing traversal service, and a chunk's own size is an
operator-chosen, bounded input, not unbounded catalog-wide work.

**Deploy/enqueue mirror the existing `verify-challenge` pattern exactly**:
`infra/ansible/playbooks/deploy-cohort-seed-bfs-job.yml` (copy-to-persistent-`rq_jobs_dir`,
targeting `hosts: workers` -- both `x86_workers` and `pi_workers`, since this job's cost
profile fits Pi's constraint) and `scripts/enqueue_cohort_seed_bfs.py` (per-worker-queue
naming, round-robin sharding, burst-worker invocation, `wait_for_jobs`/result-collection,
same as `scripts/enqueue_verify_challenge.py`).

**`score_pairs` gets a third dispatch path** alongside today's sequential and local-cursor
paths: when enabled, it shards `artist_ids` the same way, enqueues each chunk via the new
script's logic, and merges the returned per-artist `(parent, capped, failure)` results into
`parent_by_seed`/`capped_by_seed`/`failed_seeds` exactly as the existing paths already do.
Pair-reconstruction code downstream (`_pair_path`, etc.) needs no changes at all -- the
three dispatch paths only differ in *where* a chunk's BFS work runs.

## Consequences

Real fleet execution is not claimed as verified by this ADR or the PR that implements
it. I (an agent, not a fleet operator) can't SSH into `zimaworker1` or the Pi workers
from a single coding session -- running the actual Ansible deploy and
`enqueue_cohort_seed_bfs.py` against real hardware, and confirming real throughput, is
Erich's own step, the same posture `AGENTS.md` already takes for real Discogs ingestion.
`make check` covers the job body's correctness via the synthetic cross-check test only.

A worker that hasn't replicated the relevant one-hop snapshot (ADR 0025) simply can't be
targeted yet -- this ADR doesn't change replication; an operator still runs
`make replicate-x86`/`make replicate-pi` first.

## Validation

`make check` green, including the new cross-check test (synthetic fixture, no real
fleet). Real fleet verification -- deploy, enqueue, measure actual throughput across
`zimaworker1` and the Pi fleet -- is explicitly **not** exercised by this change; report
it as unverified until Erich runs it himself.

## Revisit trigger

Revisit chunk sizing (currently: even round-robin split across available workers, no
capability-weighting) once Erich has real measured throughput from the actual fleet --
`zimaworker1` and the master share the same Celeron J3455 tier per this session's
hardware check, so even splitting may already be reasonable, but that's untested
assumption, not measurement. Revisit whether `cohort_seed_bfs_job.py` could safely
import `networked_players_graph_core` directly (removing the hand-maintained-mirror
duplication) if Pi worker venvs are ever deliberately widened to include it -- today's
exclusion is about keeping worker venvs lean generally, not a hard technical blocker
specific to `CreditGraph`.
