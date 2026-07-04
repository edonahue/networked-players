# Docker Swarm

Docker Swarm is the current orchestration direction because the first cluster needs a small control plane and a clear distinction between managers, workers, services, and tasks.

The first proof should deploy one harmless multi-architecture service, verify placement on each worker, remove and rejoin a worker, and document single-manager recovery. Stateful services remain pinned to the coordination host; Swarm does not make local storage distributed.

No production stack or join token belongs in this repository.

## Coordination-host services (dev loop)

`docker-compose.coordination.yml` runs Postgres and Redis on the coordination host
for local development. It is intentionally **not** a Swarm stack — stateful services
stay pinned here. Credentials come from a git-ignored `.env`:

```bash
cd infra/swarm
cp .env.example .env      # then edit; never commit .env
docker compose -f docker-compose.coordination.yml up -d
docker compose -f docker-compose.coordination.yml ps
```

Or run `./deploy-coordination.sh`, which generates `.env` automatically with a
random password (idempotent, safe to re-run).

Both services bind to loopback only.

## Portainer (Swarm visibility)

`docker-compose.portainer.yml` runs Portainer CE, a web UI for inspecting Swarm nodes,
services, and containers. Like the coordination-host services above, it is intentionally
**not** a Swarm stack — Swarm's `--publish` always binds `0.0.0.0`, which is unacceptable
for an unauthenticated-until-first-login admin UI with full `docker.sock` access. See
`docs/decisions/0008-portainer-swarm-visibility.md` and
`docs/decisions/0009-portainer-tailscale-access.md` for the reasoning.

```bash
./scripts/install-tailscale.sh    # one-time; joins this host to your tailnet
cd infra/swarm
./deploy-portainer.sh             # auto-binds to the Tailscale IP if connected,
                                   # else falls back to loopback-only
```

The script prints exactly which URL to use. Never bind this to a LAN interface or
`0.0.0.0` directly — only loopback (SSH tunnel) or Tailscale (tailnet-only).

### Portainer Agent (per-node stats)

Portainer's Swarm environment already lists every joined node (role,
availability) via the manager's own Docker API — no extra deployment
needed for that. **Live per-node CPU/RAM/disk stats** need the Portainer
Agent, deployed once real multi-node data exists to look at (per
[ADR 0008](../../docs/decisions/0008-portainer-swarm-visibility.md)'s own
revisit trigger — this extends that decision, it isn't a new tool or a new
ADR).

```bash
./deploy-portainer-agent.sh
```

Deploys `portainer/agent` as a global Swarm service (one per node
automatically, including future workers) with **no published port** —
reachable only over an internal Swarm overlay network — then connects the
existing plain Portainer container onto that same network so it can reach
the agent. In Portainer's UI, switch (or add) the environment to Agent
mode at `tasks.agent:9001` to unlock the per-node stats; this last step is
a UI action, not automatable from the CLI.

Prometheus/Grafana/cAdvisor remain deliberately deferred — a bigger,
separate, ADR-worthy decision if deeper metrics/alerting are ever needed,
not built alongside this.

## Jobs broker (cluster benchmarking)

`docker-compose.jobs-broker.yml` runs a dedicated Redis for RQ job-queue
traffic — separate from the coordination stack's loopback-only Redis above,
which never carries job traffic. This is the **first LAN-reachable service**
in this repository: bound to the coordination host's real Ethernet address
(never `0.0.0.0`), password-protected, and deliberately **not** a standing
service. See [ADR 0019](../../docs/decisions/0019-cluster-benchmark-rq-job-broker.md).

```bash
./deploy-jobs-broker.sh          # generates local/jobs-broker.env on first run
# ... run make cluster-benchmark-distributed (see infra/ansible/README.md) ...
./deploy-jobs-broker.sh --down
```

## Catalog-data server (remote dataset access)

`docker-compose.catalog-data.yml` serves the processed dataset tree
(`local/processed/`) **read-only over LAN HTTP** so remote workers can read
data that physically lives only on this host's NVMe — see
[ADR 0024](../../docs/decisions/0024-http-readonly-catalog-data-access.md)
for why HTTP beat NFS (client mounts need apt, forbidden on the x86 worker),
MinIO (no measured need for S3 semantics), and rsync replication. Range
requests make remote DuckDB/PyArrow parquet reads fetch only the columns and
row groups a query touches; clients enumerate files from each dataset's own
`manifest.json` (`dataset_locator.py` in `packages/catalog`), never by
globbing. Same posture as the jobs broker: LAN-interface-bound (never
`0.0.0.0`), not a standing service.

Access policy per ADR 0024: the x86 worker may read full-dataset partitions;
Pi 3Bs only ever read the one-hop dataset or bounded partitions.

```bash
./deploy-catalog-data.sh         # generates local/catalog-data.env on first run
# ... remote-worker session (see infra/dask/README.md) ...
./deploy-catalog-data.sh --down
```

## Swarm init / join runbook

Initialize the manager on the coordination host and join the workers. Real tokens and
addresses stay out of Git — capture them locally only. `./init-swarm-manager.sh`
automates the manager-side steps below (idempotent) and persists the join token/
command to `local/swarm/` (git-ignored).

```bash
# On the coordination host (manager), one-time:
./init-swarm-manager.sh
```

For each Pi worker, in order — this is the full, current sequence (kept in
sync as of the fourth worker's bring-up; if you're reading an older copy of
this file, check `infra/ansible/README.md`'s "Mutating playbooks" section
for anything newer):

1. **SSH bootstrap** (one-time key setup): `infra/ansible/bootstrap-worker-ssh.sh`
2. **Health check** (read-only): `make cluster-health ARGS="--limit workers"`
3. **Benchmark** (read-only-safe, optional but cheap): `make cluster-benchmark ARGS="--limit workers"`
4. **Onboard** (installs Docker, adds the SSH user to the `docker` group —
   [ADR 0015](../../docs/decisions/0015-fleet-onboarding.md)):
   `make cluster-onboard ARGS="--limit workers --ask-become-pass"`
5. **Harden** (arms the hardware watchdog, configures Docker log rotation —
   `pi_workers` only, not the broader `workers` group; see ADR 0022):
   `make harden-workers ARGS="--ask-become-pass"`
6. **Equip** (baseline tooling — `uv`, DuckDB CLI, `jq`/`redis-tools`, a
   `redis`/`rq`/`duckdb` venv — `pi_workers` only, ADR 0022):
   `make equip-workers ARGS="--ask-become-pass"`
7. **Join** (guarded, one worker at a time —
   [ADR 0017](../../docs/decisions/0017-guarded-swarm-worker-join-automation.md)):
   `CONFIRM=yes ARGS="--limit worker-01 --ask-become-pass" make cluster-swarm-join`
8. **Verify from the manager**: `sudo docker node ls` — confirm `Ready`/`Active`,
   no unexpected manager promotion.
9. **Resilience check** (optional but recommended — real proof, not inferred):
   `infra/ansible/reboot-and-verify-worker.sh <alias>`
10. **Cluster-vs-single-node benchmark** (optional, once joined workers
    exist): deploy the job body
    (`infra/ansible/run-deploy-rq-benchmark-job-local.sh --limit workers`),
    then see infra/ansible/README.md's "Cluster-vs-single-node comparison"
    section.

Steps 2–6 can run against `--limit workers` (all newly-added workers at once,
`serial: 1` internally) if every worker shares the same sudo password;
otherwise scope each to `--limit <one-worker>` individually. Step 7 always
stays one worker at a time regardless.

No separate step is needed for Portainer Agent visibility — it's deployed as
a **global** Swarm service, so it automatically starts on any node that joins
later, including this one, with no redeploy required.

`swarm-join.yml` reads the token from `local/swarm/worker-join-token.txt` and the
manager address from `local/swarm.env` itself — never hand-type either. It no-ops
cleanly if a worker already reports an active Swarm state, and never calls `docker
swarm leave` or promotes a node automatically.

### x86_64 Swarm worker (ZimaBoard, `x86_workers`)

The second ZimaBoard was originally `optional_build_nodes` (ADR 0015) — a
standalone, non-Swarm box. It has since joined the Swarm as a dedicated
worker instead (ADR 0022, amending 0015); `optional_build_nodes` has no
populated hardware right now.

This host follows the **same runbook steps 1-4 and 7-9** as a Pi worker —
it's a flat member of the `workers` group, so `health.yml`, `benchmark.yml`,
`onboard.yml`, and `swarm-join.yml` all reach it unchanged. It **skips step
5** (hardening): `harden-workers.yml` stays scoped to `hosts: pi_workers`
specifically, since it encodes real Pi-specific facts (a Pi's hardware
watchdog device, SD-card write-endurance log-rotation reasoning) that don't
hold here.

**Step 6 (equip) uses a different playbook, `equip-x86-workers.yml`, not
`equip-workers.yml`** (ADR 0023) — same lean venv shape (`uv`, DuckDB CLI, a
`redis`/`rq`/`duckdb` venv) but **no `apt` task at all**, since this host's
package state is fragile and every tool here has a safe user-local
install: `make equip-x86-workers ARGS="--limit x86-worker-01 --ask-become-pass"`.
This closes the gap this section used to describe as "no equivalent
playbook exists yet." A full x86_64 ZimaBoard could still reasonably run the
*full* `packages/catalog` stack (`uv sync --extra dev`) directly rather than
this lean venv — that remains a real, separate, not-yet-built task, not
something to assume is covered.

Once equipped, this host participates in the same RQ/Dask fleet work the
Pi's do — `scripts/cluster_benchmark_distributed.py`, `run-rq-burst-worker.yml`,
and the on-demand `run-dask-worker-burst.yml` all reach it via the flat
`workers` group, no separate targeting needed. Its resource limits are
scaled up for real higher capability via `group_vars/x86_workers.yml`
(ADR 0023), not held to the Pi's 1GB-sized ceilings — see
`infra/ansible/README.md`'s equivalent section for the exact vars.

`optional_build_nodes` stays defined in the example inventory and in
`onboard.yml`'s second play (verifies Docker is present, installs nothing)
for any future hardware that fills that standalone-workstation role again.

### Worker-only smoke test

```bash
make cluster-smoke-test
```

`infra/swarm/run-worker-smoke-test.sh` deploys a uniquely named, global-mode,
worker-only service (`--constraint node.role==worker`, no published port),
verifies the image is actually multi-arch first (`docker manifest inspect`),
waits for one Running task per worker, and removes the service in a cleanup
trap even on a partial failure.

> **Real audit finding, fixed:** an earlier version of this runbook combined
> `--mode global` with an explicit `--replicas 1` — invalid/contradictory,
> since `--replicas` only applies to replicated mode — and had no placement
> constraint at all, so it would have scheduled onto the manager too. Use the
> script above, not a hand-typed `docker service create`.

### One-worker recovery drill

Separate, explicit, destructive — not part of onboarding. Run only after the
fleet is stable and smoke-tested:

```bash
./infra/swarm/run-worker-recovery-drill.sh --yes-i-am-sure --worker worker-01
# then, to rejoin cleanly:
CONFIRM=yes ARGS="--limit worker-01 --ask-become-pass" make cluster-swarm-join
```

Drains the worker, waits for its tasks to clear, removes it from the Swarm, and
prints the exact rejoin command — it does not auto-rejoin.

Pin stateful services to the manager with a placement constraint
(`--constraint 'node.role==manager'`); never schedule Postgres/Redis onto a Pi worker.

## Backup and recovery

Both the coordination stack above and this manager's own Swarm CA/raft state
have backup/restore tooling (`make backup-coordination`, `make
backup-swarm-manager`, and their `restore-*` counterparts) — see
[ADR 0016](../../docs/decisions/0016-state-backup-and-recovery.md) and
`docs/OPERATOR_SETUP.md`'s "Backup and recovery" section for the full
runbook, both live-tested on this host 2026-07-02.
