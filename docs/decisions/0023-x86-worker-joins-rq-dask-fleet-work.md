# ADR 0023: The x86_64 Swarm worker joins RQ/Dask fleet work, at a higher-capability tier

- **Status:** Amended by ADR 0034
- **Date:** 2026-07-04

## Context

ADR 0022 made the second ZimaBoard (`x86_workers`) a genuine Swarm worker, but stopped at Swarm membership — it didn't participate in the RQ or Dask work the three Pi 3B workers (`pi_workers`) already do. Two earlier decisions assumed a Pi-only or manager-only world that no longer matches reality:

- [ADR 0020](0020-dask-jupyter-interactive-cluster-compute.md) placed standing Dask workers on the coordination host only and gave the (then non-Swarm) "optional build node" its own separate, plain `docker-compose.dask-worker-remote.yml` mechanism — stale now that this box is a Swarm member.
- [ADR 0021](0021-canonical-benchmarks-and-dask-rq-isolation.md) built `run-rq-burst-worker.yml`/`run-dask-worker-burst.yml`'s `systemd-run --user` isolation with hardcoded, Pi-sized resource limits (`Nice=15`, `MemoryMax=600M`, `--memory-limit 400MiB`, `--nthreads 1`, etc.) — reasonable when only Pi 3B's existed, but wrong to apply unchanged to a host with 4 CPUs and 7.6GB RAM.

ADR 0022's own Revisit trigger named this exact moment: "Revisit if this worker ever needs its own hardening/equip pass... that's new `x86_workers`-scoped playbook work, not an extension of `harden-workers.yml`/`equip-workers.yml`."

**Explicitly out of scope for this decision:** the coordination host ("master") stays scheduler/manager-only. Its existing 2 standing `dask-worker` replicas (`docker-stack.dask.yml`, placement-constrained to `node.role == manager`) are untouched; enabling a portion of the master's own capacity for worker tasks is a separate, later decision.

## Decision

1. **New playbook `equip-x86-workers.yml`, not an extension of `equip-workers.yml`.** Same lean tool shape (`uv`, DuckDB CLI, a `uv`-managed venv with `redis`/`rq`/`duckdb` — no `lxml`/`pyarrow`) via the same user-local curl installs `equip-workers.yml` already uses, plus the same one-time `loginctl enable-linger` `harden-workers.yml` does for `pi_workers` (required for `systemd-run --user`). **No `apt` task at all**, not even a conditional one — this host's package state is fragile (previously tangled with Debian testing, held `libc6`/`libc-bin`/`locales`), and every tool here already has a safe, user-local alternative to an apt package.
2. **RQ/Dask resource limits are now group_vars-parameterized, not hardcoded constants.** `run-dask-worker-burst.yml` gained `dask_worker_nice`, `dask_worker_io_priority`, `dask_worker_systemd_memory_max`, `dask_worker_memory_limit`, `dask_worker_nthreads`, `dask_worker_nworkers`; `run-rq-burst-worker.yml` gained `rq_worker_systemd_memory_max`. Defaults match the exact original Pi-sized values, so Pi behavior is unchanged. `group_vars/x86_workers.yml` overrides the *capability* knobs (memory limits, thread/worker counts) to values sized from this host's real measured headroom (~6.7GB available even while already running Docker+Swarm+Portainer Agent) — **but not the niceness/IO-priority knobs**, which stay identical across both groups: Dask yielding to RQ is a fleet-wide contention policy, not a hardware-capability question.
3. **`scripts/cluster_benchmark_distributed.py`'s `load_workers()` reverts to the flat `workers` group.** It was narrowed to `pi_workers` earlier in the same session specifically because `x86_workers` lacked the RQ venv; Decision 1 closes that gap, so the original, simpler, inclusive targeting is correct again.
4. **Chunk-splitting stays an even split** across however many hosts are in `workers` (now four). Proportional splitting by real hardware capability is reasonable future work, not built here — see Revisit trigger.
5. **`docker-compose.dask-worker-remote.yml` (ADR 0020's non-Swarm "optional build node" worker) is now unused for this specific box.** Kept, not deleted, in case a future different non-Swarm build node needs that mechanism again.

## Consequences

The fleet's RQ/Dask work now spans four hosts instead of three, with the newest and most capable one running proportionally larger jobs per invocation (bigger `--nthreads`/`--memory-limit`) without any playbook fork — the same two files serve both hardware classes correctly via group_vars, rather than a Pi-only file plus a hand-maintained x86 duplicate. The coordination host's own role is unchanged by this decision. A new gap this creates, left open deliberately: work is still split evenly across workers regardless of capability, so `x86_workers`' extra headroom isn't yet used to take a proportionally larger *share* of a distributed run — only to run its own even share faster and with less contention risk.

## Validation

`ansible-playbook --syntax-check` passes for `equip-x86-workers.yml` and both retargeted playbooks against the example inventory. `ansible-inventory --host <x86 worker>` against the example inventory shows the new group_vars resolving correctly (`dask_worker_memory_limit: 4GiB`, `dask_worker_nthreads: 4`, etc.), confirmed live. `scripts/cluster_benchmark_distributed.py`'s `load_workers()` returns all four real hosts (three Pi's plus the x86 worker), confirmed live against the real local inventory. Live fleet validation (real `equip-x86-workers` run, a real Dask burst worker registering from this host alongside the coordination host's standing workers, a real `cluster-benchmark-distributed` run including this host) is tracked in this session's own operational record, not restated here per ADR 0018's local-only-results policy.

## Revisit trigger

Revisit proportional chunk-splitting (Decision 4) if a real distributed run's per-host timing data shows the even split leaves meaningful throughput on the table. Revisit if the coordination host's own capacity is later opened up for worker tasks (explicitly deferred here) — that's a new decision about the master's role, not an extension of this one. Revisit the `x86_workers` resource-limit values themselves if real measured behavior under production-scale load (not just a benchmark probe) shows the current headroom estimate was wrong in either direction.

**Already active, 2026-07-04:** the operator raised `dask_worker_memory_limit`/`dask_worker_systemd_memory_max` from an initial conservative `4GiB`/`5G` to a deliberately aggressive `6GiB`/`7G` (real local `group_vars/x86_workers.yml`), before any real benchmark/notebook run had exercised this host's Dask worker under load. This leaves only ~600MB genuinely free outside the cgroup for OS/Docker/Swarm/RQ (plus ~1GB swap as a slow fallback) — reevaluate this specific value once real peak-usage data exists from an actual distributed run on this host, not just the real headroom this ADR's Decision 2 was originally sized from.
