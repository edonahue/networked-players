# ADR 0020: Adopt Dask + Jupyter for interactive cluster compute

- **Status:** Accepted
- **Date:** 2026-07-03

> **Amended 2026-07-03.** After the initial deploy and real end-to-end
> validation (below), the operator asked to move Jupyter from loopback-only
> to LAN-reachable (via `coordination-host.local` mDNS), for convenience over an SSH
> tunnel on a private home network. `docker-compose.jupyter.yml`'s port bind
> is now `${JUPYTER_BIND_IP:-127.0.0.1}`, auto-detected by
> `infra/dask/deploy-dask.sh` the same way `deploy-jobs-broker.sh` already
> detects a LAN IP (never `0.0.0.0`) — set `JUPYTER_BIND_IP=127.0.0.1` in
> `local/dask.env` to opt back out. `JUPYTER_TOKEN` stays mandatory either
> way, but the token now travels over plain HTTP on the LAN rather than
> inside an SSH tunnel's encryption — an accepted tradeoff for a private
> home LAN, not a substitute for a real secret if this host is ever
> reachable beyond it. This narrows the "Decision" and "Consequences"
> sections below (Jupyter is no longer loopback-only *by design*, only by
> default); the reasoning for why it was loopback-only in the first place
> (a sensitive, arbitrary-code-execution surface) still stands and is why
> the token remains mandatory and the default remains loopback.
>
> Two real deploy-time bugs surfaced during that same validation session,
> fixed and recorded here rather than pretending the first pass was clean:
> (1) the plain-compose Jupyter project and the Swarm stack both defaulted
> to the same implicit network name (`dask_default`), so `docker stack
> deploy` failed with a network-already-exists error — fixed by giving the
> stack an explicit, named `attachable: true` overlay network (`dask-net`,
> resolving to `dask_dask-net`); (2) even without that collision, Jupyter
> had no path to resolve `tcp://dask-scheduler:8786` by hostname, since a
> plain `docker compose` container and a Swarm-managed service aren't on
> the same network by default — fixed by having `deploy-dask.sh` run
> `docker network connect dask_dask-net dask-jupyter-1` after both are up,
> the same pattern `infra/swarm/deploy-portainer-agent.sh` already uses to
> let the plain Portainer container reach the Agent service.

> **Amended by [ADR 0023](0023-x86-worker-joins-rq-dask-fleet-work.md)
> (2026-07-04):** the "Pi 3B workers are excluded... the optional build node
> is not a Swarm member and cannot join a Swarm stack at all" scoping in the
> Decision below is narrowed for the specific box ADR 0022 already moved
> into the Swarm as `x86_workers` — it now participates in on-demand Dask
> work the same way `pi_workers` does, at resource limits scaled to its real
> higher capability. The coordination host's own manager-only role, and the
> reasoning for keeping Dask's standing scheduler/worker pair there, are
> untouched. See ADR 0023 for the reasoning.

## Context

`docs/ARCHITECTURE.md` has named Dask as "an optional experiment for a
workload with real task dependencies or distributed analytical collections"
since the architecture was written, but nothing was ever built — no
Jupyter, Dask, or Ray code exists anywhere in this repo. The operator wants
an interactive way to experiment with cluster compute against this
project's existing stack (pandas/PyArrow/DuckDB, real ingested Discogs
Parquet output), and asked for research against alternatives before
committing.

Two decisions the operator made explicitly during that research changed the
initial default recommendation:

1. **Standing service, not on-demand.** The initial recommendation was a
   manually-started scaffold with minimal blast radius. The operator prefers
   a standing service "for efficient integration," conditioned on a resource
   evaluation.
2. **Pi workers should eventually participate.** No real memory-headroom data
   exists anywhere in this repo for the Pi 3B workers (1GB RAM each,
   already running Docker+Swarm+Portainer Agent+RQ+DuckDB) — only
   aspirational "must fit in 1GB" language. A Dask worker process typically
   runs 150–350MB idle per general Dask documentation (a sourced estimate,
   not a local measurement). Stacking that onto an already-tight Pi is a
   real OOM risk, and repeats exactly the kind of resource stacking
   `equip-workers.yml` already avoids by excluding `lxml`/`pyarrow`. The
   operator's resolution: measure real headroom first, and gate any Pi
   participation to when that Pi has no active/queued RQ job — explored
   further as real data comes in, not fully automated in this first pass.

## Decision

**Framework: Dask, not Ray or Spark.** Dask wins on native pandas/NumPy/
PyArrow interop (Dask DataFrame/Array are built directly on those, matching
`packages/catalog`'s existing stack) and no JVM weight (irrelevant for the
excluded Pis, but needless weight for a coordination host + optional build
node scale). It was already the project's own named forward direction
rather than introducing a fourth unnamed option. Ray is a better fit for
actor-model/ML-training workloads, not this project's analytical-collection
shape — this doesn't foreclose Ray forever, only absent a measured need per
`AGENTS.md`'s rule against introducing a new compute engine without one.

**Scope for this pass, split by trust level:**

- `dask-scheduler` + `dask-worker` (`infra/dask/docker-stack.dask.yml`): a
  real, standing **Docker Swarm stack**, placement-constrained to the
  coordination host only. This is cluster-internal traffic (scheduler↔worker
  registration and task distribution), comparable to the existing Portainer
  Agent global Swarm service, not an admin surface — a standing Swarm
  service is an appropriate mechanism for it, unlike Postgres/Redis/Portainer
  UI, which stay plain `docker compose` specifically because Swarm's
  `--publish` can't bind a specific host IP.
- `jupyter` (`infra/dask/docker-compose.jupyter.yml`): stays a plain,
  loopback-bound `docker compose` container, token-gated with no insecure
  default — this is a genuinely sensitive admin surface (arbitrary code
  execution), matching the existing Postgres/Redis/Portainer-UI pattern, not
  the Portainer-Agent pattern.
- **Pi 3B workers are excluded from this initial standing deployment.**
  `infra/ansible/playbooks/health.yml` gains a free/used-memory report
  (written to `local/benchmarks/pi-memory-headroom.md`, never published, per
  ADR 0018) as a prerequisite for any future Pi participation decision. Once
  real numbers exist, Pi participation is a **manual, explicitly on-demand**
  single burst `dask-worker` container — never a standing service on a Pi —
  and only run when that Pi has no active/queued RQ job, an operational rule
  checked manually for this pass. Automatic contention-aware gating (e.g.
  checking RQ queue depth before allowing a Dask worker to start) is
  explicit future work once there's real experience/data to design against,
  not built now.
- The optional build node is **not** a Swarm member (ADR 0015) and cannot
  join a Swarm stack at all — it gets its own plain
  `docker-compose.dask-worker-remote.yml`, run manually and directly on that
  host once reachable, pointed at the coordination host's scheduler address.
- One shared Docker image (`infra/dask/Dockerfile`) for scheduler, worker,
  and Jupyter, to avoid Dask's version-skew failure mode across
  scheduler/worker/client. No shared registry exists in this repo, and Swarm
  stacks ignore any `build:` key, so the image must be built locally on every
  node that runs a service from it (`infra/dask/deploy-dask.sh` handles this
  for the coordination host; the build-node README section documents the
  manual equivalent there).
- `notebooks/02-explore-real-discogs-catalog.ipynb` connects to a real,
  completed ingest's Parquet output via a read-only bind mount
  (`DISCOGS_PROCESSED_DIR`), not a fixture — the other two notebooks stay
  synthetic-only per the fixtures rule.

## Consequences

New container images/compose/stack files to maintain in `infra/dask/`. No
impact on the static-first public site or core ingestion path — this is
purely a workstation/coordination-host-side tool. Jupyter is gated by a
mandatory token and loopback bind, matching every other admin surface in
this repo. Dask's scheduler-worker wire protocol has no built-in
authentication, so publishing port 8786 (even LAN-scoped via `mode: host`)
makes that surface trusted-LAN-only, not defended against a malicious LAN
peer — an accepted risk for a home lab, revisited below. This ADR does not
decide anything about the Pi workers' eventual participation beyond adding
the measurement prerequisite; that remains an open, explicitly deferred
question.

## Validation

**Confirmed live, 2026-07-03**, after fixing the two deploy-time bugs noted
in the amendment above: `sudo make dask-up` succeeds end to end;
`docker service ls` shows `dask_dask-scheduler` (1/1) and `dask_dask-worker`
(2/2) `Running`; `docker network inspect dask_dask-net` lists
`dask-jupyter-1` alongside both worker containers and the scheduler,
confirming the network-join worked; `curl` against both `127.0.0.1:8888`
and `127.0.0.1:8787` returns HTTP 302 (both services actually serving
requests). Per the amendment, `ss -tln` now shows 8888 bound to the
coordination host's LAN address (not loopback) — this is the intended
current state, not a regression from the original loopback-only design.

**Pi worker participation, confirmed live 2026-07-03** (closing the revisit
trigger below): with real headroom confirmed in
`local/benchmarks/pi-memory-headroom.md` (~640–660MB available per Pi), all
three currently-joined Pi 3B workers were started as manual, on-demand Dask
workers (`run-dask-worker-burst.yml`) and tested against the real standing
scheduler. First attempt found a real bug, not just a warning: the
playbook's original unpinned `uv pip install "dask[distributed]" pandas
pyarrow` resolved newer versions than the coordination host's pinned image
(dask 2026.6.0 vs 2025.12.0) on a different Python (Debian's default 3.11
vs the image's 3.12) — severe enough that a trivial `client.submit(add, 2,
3)` targeted at the Pi worker timed out after 30s, not merely logging a
version-mismatch warning. Fixed by pinning the Pi venv to the exact same
versions as `infra/dask/requirements.txt` (which itself moved from loose
`>=/<` bounds to exact pins for the same reason — the old bound had already
been exceeded by a real upstream release) and creating the venv with `uv
venv --python 3.12` instead of whatever Python happened to be on PATH.

After that fix, all three Pi workers registered cleanly (no mismatch
warning) and correctly executed real tasks: a 500×500 numpy random-matrix
sum averaged ~0.03s per task on each Pi, versus ~0.007s on each
coordination-host worker (~4–5× slower, consistent with Pi 3B vs desktop-
class hardware, not a malfunction). A batch of 20 real tasks scattered
across all 5 registered workers (3 Pi + 2 coordination host) completed in
0.34s total, with the scheduler's own load-balancing correctly assigning
more tasks to faster workers rather than a naive even split. Memory stayed
stable throughout (~513–517MB available per Pi during the test, down from
the ~640–660MB baseline, consistent with the 200MB per-worker memory
ceiling) — no swap, no pressure. All three workers were stopped afterward,
per the design (never a standing service on a Pi).

`00-dask-cluster-smoke-test.ipynb` was subsequently run end to end and
confirmed real distributed execution across actual worker containers (two
distinct real worker addresses processed partitions, not a local-threads
fallback) — this closes that earlier open item.

**Pi memory-limit tuning, confirmed live 2026-07-03.** The initial 200MiB
per-worker ceiling was an explicit placeholder ("starting values, not
measured facts"). Tested against a real, representative single partition
(matching `parse-releases`' actual `--chunk-releases` default, not a toy
size) read via pandas/pyarrow plus a join — full numbers in
`local/benchmarks/pi-dask-real-parquet-test.md` (local-only per ADR 0018).
Qualitatively: the 200MiB ceiling was too tight for even one real
partition — Dask's own memory manager logged a high-unmanaged-memory
warning and **paused the worker mid-task**, a real functional degradation,
not just a number close to a limit. Raised to 400MiB in
`run-dask-worker-burst.yml`, chosen to leave real margin above the observed
peak while still leaving roughly half of a Pi's baseline available memory
for the OS, Portainer Agent, and RQ. Retested at 400MiB: no pause, no
warning, and the same read that took over a second at 200MiB (degraded by
memory pressure, not cold-start cost as first assumed) completed roughly
8× faster — confirming the original ceiling was hurting throughput, not
just risking an OOM.

`./infra/dask/deploy-dask.sh --down` cleans up; `git status` shows nothing
unexpected staged from `local/` paths.

## Revisit trigger

~~Revisit Pi worker participation once `local/benchmarks/pi-memory-headroom.md`
has real numbers for all joined workers.~~ **Done, 2026-07-03** — see the Pi
worker participation validation above. Remaining open question: whether to
promote this from a manual, on-demand path to something more automated
(e.g. automatic contention-aware gating against RQ queue depth) — still
explicit future work, now backed by real timing/memory data instead of
only a sourced estimate. Revisit the Dask scheduler-worker authentication
gap (TLS certificates) if this ever needs a stronger boundary than
trusted-LAN-only. Revisit promoting the build-node worker into something
more automated once that host is consistently reachable. Revisit the
framework choice itself (Ray or another engine) only if a concrete future
workload shows a measured advantage AGENTS.md's "measured implementation
need" bar would require anyway.
