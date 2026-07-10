# ADR 0019: Cluster-vs-single-node RQ benchmark, and its LAN-reachable job broker

- **Status:** Amended by ADR 0034
- **Date:** 2026-07-03

## Context

> **Amended:** ADR 0034 promotes the proven RQ broker mechanism into the standing
> capability-routed job control plane. This ADR's benchmark implementation history
> remains valid; its temporary-broker and production-mechanism deferrals do not.

`docs/ARCHITECTURE.md` names "Redis and RQ are the default direction for
simple retryable operational jobs," and `infra/ansible/playbooks/equip-workers.yml`
already installs `redis`/`rq`/`duckdb` into a venv on every Pi 3B worker. But
until now nothing actually enqueued or executed a job: `docs/BUILD_PLAN.md`
Milestone 11 explicitly flagged "committing to RQ in code" as a
settled-direction change warranting its own ADR, and this is that moment.

A second gap surfaced while building the cluster-vs-single-node benchmark
this ADR covers: the only Redis that exists anywhere in the repo
(`infra/swarm/docker-compose.coordination.yml`) is bound to `127.0.0.1` only,
by deliberate design (ADR 0010, re-confirmed live via `ss -tln`). The Pi
workers' installed `redis`/`rq` packages have nothing reachable to connect to
over the LAN. "Reuse the already-deployed Redis/RQ" was true at the *library*
level but not the *broker reachability* level — a real architectural gap,
not a missing line of glue code.

The existing per-node benchmark (`benchmark.yml`, `make cluster-benchmark`)
also only ever reports each node's throughput independently; it cannot
answer "how much faster is the same total workload when split across the
joined workers, versus run on one worker alone?" — the actual question this
work needed to answer.

## Decision

1. **A second, dedicated Redis for job-queue traffic**
   (`infra/swarm/docker-compose.jobs-broker.yml`), separate from the
   dev-loop Postgres/Redis stack. LAN-bound to the coordination host's real
   Ethernet address (auto-detected by `deploy-jobs-broker.sh`, never
   `0.0.0.0`), with a mandatory password (`requirepass`, generated
   randomly on first run, stored in git-ignored `local/jobs-broker.env`).
   Given its own explicit Compose project name (`jobs-broker`) so it never
   shares an inferred project with `docker-compose.coordination.yml` /
   `docker-compose.portainer.yml` (see those files' own `--remove-orphans`
   caution). Deliberately **not** `restart: unless-stopped` — started
   before a benchmark run, stopped after. This is the first LAN-reachable
   service in this repository.
2. **Reuse `benchmark_parse.py` unmodified as the RQ job body.** It already
   returns every field the job result needs (hostname, architecture,
   elapsed, releases/sec, peak RSS). `deploy-rq-benchmark-job.yml` copies it
   persistently (not copy-run-delete like `benchmark.yml`) to each worker's
   `~/.local/share/networked-players/rq-jobs/`, so it's importable by dotted
   path (`benchmark_parse.run_benchmark`) from a running `rq worker` process.
3. **Orchestration via a new Ansible playbook plus a coordination-host-only
   Python driver.** `run-rq-burst-worker.yml` runs `rq worker --burst`
   against a given queue on `--limit`-scoped hosts — no standing worker
   process, matching `benchmark.yml`'s own "copy, run, clean up" ethos.
   `scripts/cluster_benchmark_distributed.py` (needs the `redis`/`rq`
   Python clients, so it runs on the coordination host only, never copied to
   a Pi) enqueues a full-size job for a single-node baseline, enqueues split
   jobs across all currently-joined workers for the distributed run, and
   compares RQ's own `started_at`/`ended_at` job timestamps — not
   ansible-invocation wall-clock, which would be skewed by SSH/fork overhead
   — to compute a fair distributed-vs-baseline speedup ratio.
4. **Results are local-only by design.** This ADR is what governs that
   choice for this specific benchmark; see
   [ADR 0018](0018-benchmark-results-local-only.md) for the broader policy
   this follows. `docs/PUBLIC_PRIVATE_BOUNDARY.md`'s classification of
   benchmark *methodology* as public is unchanged — only this run's raw
   numbers stay local.
5. **Explicit non-goal:** this does not decide `packages/workers`'
   eventual production queue/execution mechanism. It proves RQ works for one
   narrow, already-bounded use (a benchmark job), not a production job
   pipeline. That remains Milestone 11's own open task.

## Consequences

The repository gains its first LAN-exposed service. Mitigations: bound to a
specific interface (never `0.0.0.0`), mandatory password, not a standing
service (only up during an active benchmark run), and it carries no
persistent data volume (job-queue state is disposable — if lost, just
re-run). This does not change ADR 0010's Consequences for the dev-loop
Postgres/Redis stack, which stays loopback-only and untouched. Enqueuing/
executing a real RQ job for the first time also means an operator error
(stale jobs left in a queue, a worker venv drifting from what
`equip-workers.yml` installed) is now a real failure mode, not merely a
Milestone 11 might-happen-later step; `assert_queue_empty()` in the Python
driver aborts loudly rather than silently mixing runs.

## Validation

`ansible-playbook --syntax-check` against `inventories/example/` passes for
both new playbooks. A real run against the currently-joined workers:
`./infra/swarm/deploy-jobs-broker.sh`, `make cluster-benchmark-distributed`,
confirm `local/benchmarks/cluster-vs-single-node.{json,md}` are written,
confirm `git status` is clean and
`git check-ignore -v local/benchmarks/cluster-vs-single-node.json` reports it
ignored, confirm `git diff --stat docs/HARDWARE.md` shows nothing (this ADR
adds no numbers there). `ss -tln` confirms the jobs broker binds only to the
detected LAN interface, never `0.0.0.0`; an unauthenticated `redis-cli`
connection to it fails.

## Revisit trigger

Revisit when `packages/workers` picks its production execution mechanism —
it may fold this broker into that decision, replace it, or leave it
benchmark-only. Revisit when the fourth Pi worker joins, to confirm
`run-rq-burst-worker.yml` is genuinely reusable unchanged (same spirit as
ADR 0017's own trigger). Revisit if the jobs broker ever needs to become a
standing service rather than started-per-run.
