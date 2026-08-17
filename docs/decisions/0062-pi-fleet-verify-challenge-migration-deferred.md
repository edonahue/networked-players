# ADR 0062: `enqueue_verify_challenge.py`'s ADR-0034 migration stays deferred

- **Status:** Accepted
- **Date:** 2026-08-17
- **Depends on:** [ADR 0034](0034-capability-routed-home-compute-platform.md), [ADR 0056](0056-unify-pi-fleet-checks-onto-capability-platform.md) (the 8-check migration this entry was left out of), [ADR 0025](0025-worker-local-dataset-cache.md) (the one-hop cache `verify_challenge_job.py` reads)

## Context

`docs/NEXT_PATH_BRIEF.md`'s "Full RQ-based Pi fleet maturity" entry has
named this as open since the post-Phase-3 cleanup pass: two scripts remain
outside the ADR 0034 capability platform that absorbed the other 8 fleet
checks (ADR 0056) — `scripts/enqueue_verify_challenge.py` and the legacy
`infra/ansible/files/rounds_check_job.py`. The entry's own "biggest
uncertainty" was never resolved: *"whether `enqueue_verify_challenge.py`'s
sharded pattern needs its own new primitive in `packages/platform`, or fits
the existing `select_worker()`/`RunRequest` shape as-is."*

Real investigation, this pass, answers that question:

**`select_worker()`/`RunRequest` support only single-worker dispatch.**
`scheduler.select_worker()` (`packages/platform/src/networked_players_platform/scheduler.py:49-86`)
filters candidate `WorkerAdvertisement`s and always returns exactly one —
least `active_jobs`, tie-broken by `last_assigned_at` then `worker_id` — or
raises `NoEligibleWorkerError`. There is no "select N workers" mode.

**The one existing multi-worker "fan-out" is sequential and redundant, not
parallel and sharded — the architectural opposite of what
`enqueue_verify_challenge.py` needs.** `scripts/submit_artifact_check.py`'s
per-host loop (ADR 0056) calls `select_worker()` once per host, filtered to
that single host, and dispatches the *same* `RunRequest` (same validator,
same artifact bytes) to prove every worker's environment agrees —
synchronously, one worker at a time (`_check_one_worker()` blocks on
`enqueue_and_wait()` before the loop advances). It was built to prove
environmental consistency, not to split one workload's input across
workers for throughput.

**`enqueue_verify_challenge.py` already implements the pattern a real
migration would need to build from scratch.** It re-verifies the published
`challenge.v2.json` artifact's evidence against each Pi's own one-hop cache
(ADR 0025) — real, live production infrastructure, deployed via
`infra/ansible/playbooks/deploy-verify-job.yml` (`make deploy-verify-job`).
It shards `challenge.v2.json`'s path list (`shard_path_ids`), assigns each
shard to a specific worker's own dedicated RQ queue
(`queue_name_for(prefix, host)`, mirroring the broker's own
`queue_name(worker_id)` per-worker-queue convention — just applied ad hoc
rather than through the platform), enqueues every shard concurrently, then
waits on the whole batch together (`wait_for_jobs`). ADR 0043's slice-8
addendum already called this "a genuinely different, already-correct
sharding pattern" when a prior cohort-check bug fix deliberately left it
untouched. This pass added real test coverage for that dispatch logic
(shard/queue/wait/aggregate — previously untested; see the companion PR),
confirming it's correct as it stands.

**`infra/ansible/files/rounds_check_job.py` is fully dead on the fleet.** No
deploy playbook exists for it (confirmed: no `deploy-rounds-check-job.yml`
anywhere under `infra/ansible/playbooks/`), no Makefile target invokes it,
and its only live caller is `build-rounds-from-dump` — a CLI command
`networked_players_graph_core/rounds.py` itself marks "LEGACY/exploratory
only." The job body's own docstring already states it is "intentionally"
excluded from the live fleet, and ADR 0056 explicitly scoped it out of the
8-check migration for the same reason.

**Migrating `enqueue_verify_challenge.py` onto the capability platform
would mean building a genuinely new primitive** — "shard input N ways,
select and dispatch to N specific workers in parallel, collect N results
together" — that doesn't exist on `packages/platform` today.
`docs/NEXT_PATH_BRIEF.md` itself only ever named the value of this
migration as *"operator confidence, not end-player-visible."* That is a
weak justification for rearchitecting a live, correctly-working production
dispatch path, especially with no live-fleet access in this working
session to verify a rewrite safely against real hardware before it ships.

## Decision

**Defer building a new capability-platform sharded-dispatch primitive.**
`enqueue_verify_challenge.py` stays exactly as it is: real, working,
ADR-0034-*adjacent* production infrastructure, not ADR-0034-*integrated*.
It is not broken, not blocking any real feature, and rewriting it onto a
not-yet-existing platform primitive for a single consumer repeats the
exact anti-pattern this repo's own convention already names: *"extract a
shared helper only once a third surface needs it"* (`docs/PHASE3_REPORT.md`,
on why a generic `research promote` command was deferred the same way).

**`rounds_check_job.py` is a deletion candidate, not a migration
candidate.** It has zero live callers on the fleet. This ADR does not
delete it — that is a separate, smaller decision this pass wasn't scoped
to make unilaterally — but names it explicitly so a future cleanup pass
doesn't have to re-derive the same investigation.

**What this is not**: not a claim that the capability platform is the
wrong long-term home for `enqueue_verify_challenge.py`'s pattern, and not
a closure of `docs/NEXT_PATH_BRIEF.md`'s "Full RQ-based Pi fleet maturity"
entry — it stays open, updated with a link to this ADR.

## Consequences

- No code or infrastructure change beyond this document and the companion
  test-coverage PR (`scripts/enqueue_verify_challenge.py`'s dispatch logic
  is now tested, but its runtime behavior and deployment are unchanged).
- `docs/NEXT_PATH_BRIEF.md`'s "Full RQ-based Pi fleet maturity" entry gets
  a pointer to this ADR, replacing the open "whether... needs its own new
  primitive" uncertainty with the resolved answer.
- A future contributor investigating this same question again can start
  from this ADR's findings rather than re-deriving them.

## Validation

No new runtime code to validate beyond the companion PR's 15 tests
(dispatch-logic coverage for `enqueue_verify_challenge.py`, verified
fail-then-pass and via `make check`). This ADR itself only records a
decision and updates `docs/NEXT_PATH_BRIEF.md`'s prose.

## Revisit trigger

Re-open this decision when either becomes true:

1. A **second** real workload needs parallel, sharded, multi-worker
   dispatch (justifying one shared primitive built once for two
   consumers, per this repo's own "third surface" convention cited
   above) — not yet the case; `enqueue_verify_challenge.py` is still the
   only consumer of this shape.
2. `enqueue_verify_challenge.py` itself needs a capability-platform
   feature it currently lacks — content-addressed input staging,
   cross-architecture worker selection, or `runtime_commit` verification
   — because of a real, observed problem (a drift incident, a
   cross-architecture Pi/x86 fleet mix), not a hypothetical one.

At that point, design the new primitive against that consumer's real
requirements, informed by `enqueue_verify_challenge.py`'s own
already-correct shape (per-worker queues, concurrent enqueue-then-collect)
as the reference implementation to generalize from.
