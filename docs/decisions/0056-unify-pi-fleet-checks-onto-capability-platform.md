# ADR 0056: unify Pi-fleet artifact checks onto the ADR 0034 capability platform

- **Status:** Accepted
- **Date:** 2026-08-04
- **Depends on:** [ADR 0034](0034-capability-routed-home-compute-platform.md), [ADR 0043](0043-connection-guesser-corrective-slice.md), [ADR 0046](0046-record-routes-productionization.md)

## Context

`docs/ROADMAP.md` §6 named one specific open item: "Consolidate those jobs
behind the ADR 0034 capability and provenance runtime." ADR 0034's runtime
(`packages/platform`) has existed since Phase 2 and, as of the Pi fleet
onboarding earlier this session, all three Pi workers plus the x86 worker
are real, live participants in it (`select_worker()`/`RunRequest`/RQ). But
the fleet's actual artifact-validation jobs — the ones giving real
confidence a published artifact still validates on real hardware — ran
through a separate, older pattern: 8 `scripts/enqueue_*_check.py` scripts,
each with its own pre-deployed job-body file
(`infra/ansible/files/*_check_job.py`) and deploy playbook
(`infra/ansible/playbooks/deploy-*-check-job.yml`), dispatching raw RQ
jobs by hostname/inventory-group rather than through the capability
platform. This was real, working, and had been run for real against the
fleet (2026-07-25) — not broken, just parallel to the newer system.

Investigating all 8 old scripts, their job bodies, and two representative
deploy playbooks before starting found that every one of the 8 checks
does the exact same shape of work: read 1 or 2 already-public JSON
artifacts, call one `networked_players_contracts` dependency-free
validator function, return `{"valid": bool, "failures": [...]}`. The
capability platform already had a workload for exactly this
(`artifact.validate`), hardcoded to two single-input validators
(`connectivity`, `playable-cohort`) used only by the cohort-artifact
check. This made the migration a real, low-risk generalization of
existing code, not a new subsystem.

## Decision

**Extend `artifact.validate` to cover all 8 real validators**, rather
than building a new workload per check. `packages/platform/workloads.py`'s
handler grew a validator table (`name -> (function, input arity)`) —
`connectivity`, `playable-cohort` (unchanged), plus `catalog`,
`album-art`, `connection-rounds`, `contributor-index`, `daily-manifest`,
`pathfinding-graph`, `record-routes` (new) — all pulled from
`networked_players_contracts`, already a hard dependency of
`packages/platform`. Input order per validator was verified against the
real old job bodies during investigation, not guessed.

**One new submission script, `scripts/submit_artifact_check.py`,
replaces eight old ones.** It reuses the exact
stage/dispatch/wait/fetch/verify machinery
`submit_research_platform_job.py` already proved against this fleet
(content-addressed `RunRequest.inputs`, ansible copy/fetch, checksum
verification) instead of raw per-host RQ queues and pre-deployed job
bodies. Content-addressed staging via `RunRequest.inputs` replaces the
old pattern's pre-deployed-artifact-plus-separate-deploy-playbook
entirely — nothing needs to be copied to a worker ahead of a check
anymore; each run stages the current artifact(s) fresh.

**Redundant fan-out is preserved deliberately, not replaced by
`select_worker()` picking one worker.** This is the one real design
tension the migration had to resolve: the old scripts intentionally
dispatched the *same* check to *every* targeted worker (proving each
worker's own environment independently validates, catching per-worker
drift) — a fundamentally different intent than `select_worker()`, which
picks exactly one best worker per `RunRequest`. The new script preserves
the old, real value by resolving the target inventory group to its
member hosts (same mechanism the old `_fleet_check.load_workers` used)
and dispatching one independent `RunRequest` per worker explicitly
(`select_worker` in its already-precedented single-candidate/
`--worker-id`-filtered form), not by asking the scheduler to choose.

**The old pattern is retired, not kept running in parallel.** Once the
extended `artifact.validate` workload and the new submission script were
real-verified against the live fleet — a 1-input and a 2-input validator
individually, a full redundant-fan-out run of `catalog` across all three
Pi workers, then the remaining five fixed-artifact validators plus one
ad hoc validator, all passing — the old 8 enqueue scripts, their shell
wrappers, `scripts/_fleet_check.py`, `scripts/_artifact_staging.py`,
the 7 job-body files, the 8 deploy playbooks plus `stage-artifact.yml`,
their `run-deploy-*-check-job-local.sh`/`run-stage-artifact-local.sh`
wrappers, and their now-superseded tests were removed in the same
change. Leaving two working, overlapping fleet-validation systems
running indefinitely was judged worse than a clean cutover once the new
path was proven equivalent — this project's own convention (measure,
then commit) applied to retiring code, not just adopting it.

**One thing intentionally out of scope**: `infra/ansible/files/
rounds_check_job.py` and its `rounds_failures` validator (a legacy,
Record-Routes/Connection-Guesser-unrelated contract, per ADR 0046) has
no corresponding `enqueue_*_check.py` script and was never part of the 8
being consolidated — left untouched, not silently caught up in this
migration's file deletions.

## Consequences

- `make <validator>-check-distributed` targets are unchanged in name and
  `ARGS=` interface; the separate `deploy-<validator>-check-job` targets
  are gone (nothing left to pre-deploy). `docs/OPERATOR_SETUP.md`'s two
  Pi-ambient-check sections were rewritten into the new one-step
  invocation, and — as a side effect of the rewrite — now correctly
  document `contributor-index`/`pathfinding-graph`, which the old docs
  never mentioned despite the checks existing (Phase 2 Slice N).
- Real fleet observations before this change (2026-07-25) and the
  real re-verification this migration performed (2026-08-04) are both
  recorded in `docs/OPERATOR_SETUP.md` as dated, non-standing
  observations (ADR 0018) — not evidence the fleet is always healthy.
- `scripts/tests/` is now empty (its only contents validated the retired
  pattern) and was dropped from `pyproject.toml`'s pytest `testpaths`.

## Revisit trigger

If a future check needs more than two input artifacts, or a validator
whose signature doesn't fit the `(artifacts...) -> list[str]` shape,
`artifact.validate`'s table-based dispatch will need a real redesign —
not a blind extension of the arity-counting scheme used here.
