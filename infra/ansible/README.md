# Ansible

Ansible is planned to provide repeatable baseline configuration for the coordination host and four worker nodes.

## Capability runtime

ADR 0034 adds an independently packaged worker runtime. Build it only from a clean
commit, then deploy the exact commit-addressed bundle:

```bash
make platform-build
make platform-deploy ARGS="--limit pi_workers"
make platform-status
```

`deploy-platform-runtime.yml` installs the contracts/platform wheels into a versioned
user-local virtual environment, verifies imports, switches the `current` symlink, and
manages one standing RQ worker plus a 30-second capability heartbeat through user
systemd. It contains no `become` task. Linger must already be enabled; the playbook
fails rather than silently escalating if it is not.

Real inventories define an opaque `platform_worker_id` and policy tags per host. Job
requests use those advertised capabilities, never inventory hostnames. The broker URL
remains private and is written to a mode-0600 worker environment file with Ansible
`no_log` enabled.

Early playbooks should remain narrow:

1. verify supported operating system and architecture;
2. create a non-root service account;
3. install required system packages;
4. configure container runtime prerequisites;
5. report storage, memory, temperature, and time synchronization;
6. prove idempotent reruns.

Commit only example inventories. Real inventory, host variables, addresses, and vault material remain local and ignored.

## Layout

```text
ansible.cfg                                       defaults; points at the example inventory
playbooks/health.yml                              read-only facts + health checks (Phase 1)
playbooks/benchmark.yml                           read-only-safe CPU/memory probe per node
playbooks/harden.yml                               coordinator hardening, state-changing (ADR 0014)
playbooks/onboard.yml                              Pi worker + build-node onboarding (ADR 0015)
playbooks/swarm-join.yml                          guarded, one-worker-at-a-time Swarm join (ADR 0017)
playbooks/harden-workers.yml                      Pi 3B worker hardening: watchdog, Docker log rotation
playbooks/equip-workers.yml                       Pi 3B worker baseline tooling: uv, duckdb, jq, venv
playbooks/equip-x86-workers.yml                   x86_64 worker baseline tooling: uv, duckdb, venv, no apt (ADR 0023)
playbooks/deploy-rq-benchmark-job.yml             persist benchmark_parse.py as an RQ job body (ADR 0019)
playbooks/deploy-cohort-check-job.yml             persist cohort_artifact_check_job.py as an RQ job body
playbooks/run-rq-burst-worker.yml                 burst `rq worker` against one queue (ADR 0019)
playbooks/run-dask-worker-burst.yml               manual, on-demand Dask worker for one worker host (ADR 0020/0023)
files/benchmark_parse.py                          standalone probe copied to each node by benchmark.yml
  (also reused, unmodified, as the RQ job body above)
files/cohort_artifact_check_job.py                hand-maintained mirror of two graph-core cohort
  validators; copied to each Pi as an RQ job body by deploy-cohort-check-job.yml above
run-health-local.sh, run-benchmark-local.sh,      guarded local entry points (share run-playbook-local.sh);
  run-onboard-local.sh, run-swarm-join-local.sh,  all forward extra args, e.g. --limit workers --check
  run-deploy-rq-benchmark-job-local.sh,
  run-deploy-cohort-check-job-local.sh,
  run-rq-burst-worker-local.sh, run-dask-worker-burst-local.sh,
  run-equip-x86-workers-local.sh
bootstrap-worker-ssh.sh                           one-time passwordless SSH setup for the workers group
inventories/example/hosts.yml                     example hosts (placeholder names)
inventories/example/group_vars/all.yml            example shared variables
inventories/example/group_vars/workers.yml        example Pi 3B worker variables (SSH user, key, Swarm addrs)
inventories/example/group_vars/pi_workers.yml     example pi_workers variables (defaults-only, ADR 0022)
inventories/example/group_vars/x86_workers.yml    example x86_workers variables (RQ/Dask resource limits, ADR 0023)
inventories/example/group_vars/optional_build_nodes.yml  example build-node variables
inventories/example/host_vars/*.yml               example per-host variables (RFC 5737 addresses)
```

## First run

The `health.yml` playbook is **read-only**: it gathers facts and reports/asserts
architecture, free space, time sync, and SoC temperature, changing nothing. It is safe
to run repeatedly as first contact with new hardware.

```bash
cd infra/ansible
cp -r inventories/example inventories/local   # then edit with real hosts (git-ignored)
ansible-playbook -i inventories/local/hosts.yml playbooks/health.yml
```

Or use the guarded wrapper (`./run-health-local.sh`), which also installs
`ansible-core` via `uv tool install` if it isn't already on `PATH`. All the
`run-*-local.sh` wrappers forward extra arguments to `ansible-playbook`, so
`./run-health-local.sh --limit workers --check --diff` works as expected.

## Bootstrapping worker SSH access

Before Ansible can manage a fresh Pi worker, the coordinator needs
passwordless SSH to it. `./bootstrap-worker-ssh.sh` generates a dedicated
keypair (`~/.ssh/networked-players-cluster_ed25519`, never overwrites an
existing one), reads the `workers` group straight out of the real local
inventory (no IP/hostname hardcoded in the script itself, so it's reusable
unchanged for a later fourth worker), and copies the public key to each
host with `ssh-copy-id` — prompting for that host's password, stopping
immediately if any host fails, and independently re-verifying
non-interactive SSH to every host afterward. Never uses `sshpass`, never
disables host-key checking.

```bash
./bootstrap-worker-ssh.sh
```

**Dedicated automation account (future hardening, not done yet):** this
first bring-up uses each Pi's existing personal account directly (set via
`ansible_user` in `group_vars/workers.yml`), not a separate `deploy`
service account. A dedicated automation account is a reasonable later
hardening step — smaller blast radius, easier to audit or revoke
independently of a personal login — but isn't required to start, and
isn't introduced here to avoid the risk of a lockout on an account the
operator hasn't administered before. Revisit once the fleet is stable.

## Benchmarking

`playbooks/benchmark.yml` is read-only-safe like `health.yml` (no package installs,
no accounts changed — it copies a small script, runs it, deletes it) but is
its own playbook rather than folded into `health.yml`, since it exercises a
real CPU/memory workload rather than just reading facts. Run it *after*
`health.yml` confirms a node is reachable and healthy, same layering
`onboard.yml` uses.

The probe (`files/benchmark_parse.py`) is a small, dependency-free (stdlib
only) script — deliberately **not** the production Discogs parser in
`packages/catalog` — that models the same bottleneck already profiled for
real (`docs/DATA_SIZING.md`'s "Real profiling" section: repeated per-child
XML text lookups). Zero pip/apt installs needed on any node, which matters
for untested 1GB-RAM ARM64 Pi 3B hardware. Results report hostname,
architecture, CPU count, elapsed time, and peak RSS as one JSON line per
node, annotated with its inventory group for cross-node-type comparison.

```bash
./run-benchmark-local.sh
BENCHMARK_ITERATIONS=50000 ./run-benchmark-local.sh   # more iterations for noisy/fast hardware
```

Per [ADR 0018](../../docs/decisions/0018-benchmark-results-local-only.md),
real measured numbers are no longer transcribed into a committed doc — run
the benchmark yourself against your own hardware to see current numbers;
`docs/HARDWARE.md` only tracks the method now.

### Cluster-vs-single-node comparison

`make cluster-benchmark-distributed` answers a different question than the
per-node numbers above: how does the same total workload's aggregate
throughput look distributed across the joined Pi workers versus run on one
worker alone? It reuses the same probe (`benchmark_parse.py`, deployed
persistently by `playbooks/deploy-rq-benchmark-job.yml`) as an RQ job body,
fanned out with `playbooks/run-rq-burst-worker.yml` against a dedicated,
LAN-reachable jobs-broker Redis (`infra/swarm/docker-compose.jobs-broker.yml`
— started deliberately, not a standing service). See
[ADR 0019](../../docs/decisions/0019-cluster-benchmark-rq-job-broker.md) for
why this needed its own broker rather than reusing the loopback-only
dev-loop Redis.

```bash
./infra/swarm/deploy-jobs-broker.sh
./infra/ansible/run-deploy-rq-benchmark-job-local.sh --limit workers
make cluster-benchmark-distributed
./infra/swarm/deploy-jobs-broker.sh --down
```

Results — full per-node breakdown, aggregate job span, and the
distributed-vs-baseline speedup ratio — are written to `local/benchmarks/`
only, per ADR 0018; nothing here is published.

## Resilience testing

`reboot-and-verify-worker.sh` answers "if a worker loses power, does it
reconnect to the Swarm automatically?" for real, rather than inferring it
from config: it records a worker's current Swarm node ID, reboots it,
waits for SSH to come back, then confirms the manager sees the **same**
node ID return to `Ready`/`Active` (a different ID would mean it needed a
fresh join, not an automatic rejoin). Real, brief downtime for that one
worker — same gating spirit as the recovery drill in
`infra/swarm/README.md`.

```bash
./reboot-and-verify-worker.sh worker-01
```

## Mutating playbooks

Two playbooks actually change state, each behind its own ADR — treat them as a
different risk category than the read-only `health.yml`:

- `playbooks/harden.yml` ([ADR 0014](../../docs/decisions/0014-coordination-host-hardening.md)):
  `hosts: coordinators` only — persistent journald, hardware watchdog, Docker log
  rotation, swappiness tuning.
- `playbooks/onboard.yml` ([ADR 0015](../../docs/decisions/0015-fleet-onboarding.md)):
  onboards the `workers` group (installs Docker, prints the real `docker swarm join`
  command; `serial: 1` — one Pi 3B at a time, easier to diagnose) and the
  `optional_build_nodes` group (verifies Docker is present). Run
  *after* `health.yml` confirms a node is reachable and healthy. Prepares and
  verifies only — the actual Swarm join is a separate, more tightly guarded step
  (below); see `infra/swarm/README.md`'s runbook.
- `playbooks/swarm-join.yml` ([ADR 0017](../../docs/decisions/0017-guarded-swarm-worker-join-automation.md)):
  the guarded, one-worker-at-a-time Swarm join that ADR 0015 originally left fully
  manual. Requires `-e confirm_swarm_join=true` and `--ask-become-pass`; always
  invoke with `--limit` against exactly one worker. No-ops if the target is
  already an active Swarm member; never leaves another Swarm automatically; never
  promotes a node to manager.
- `playbooks/harden-workers.yml` — narrower, worker-scoped counterpart to
  `harden.yml`'s coordinator hardening (ADR 0014's own Revisit trigger named this
  moment). Arms the Pi's hardware watchdog and configures Docker log rotation.
  Deliberately skips journald-persistence and swappiness tasks — confirmed live
  that journald is already persistent on these Pis and no swap exists, so those
  tasks would be no-ops. Scoped to `hosts: pi_workers`, not the broader
  `workers` group (ADR 0022) — this play's reasoning is Pi-specific and must
  not run against a non-Pi Swarm worker.
- `playbooks/equip-workers.yml` — speculative-but-grounded baseline tooling:
  installs `jq`/`redis-tools` (via `baseline_packages`, first playbook to actually
  consume that var), `uv`, the DuckDB CLI, and a small `uv`-managed venv
  (`redis`, `rq`, `duckdb`) at `~/.local/share/networked-players/worker-venv`.
  Deliberately does **not** install `lxml`/`pyarrow`/`packages/catalog` — those
  are the release-parsing pipeline's dependencies, scoped by `AGENTS.md` to the
  coordination host or optional workstation, never a Pi job. Also scoped to
  `hosts: pi_workers` (ADR 0022) — this play runs a real `apt install`, which
  must never touch a non-Pi worker's package state without a separate decision.

`workers` is now a mixed-architecture group: the three Pi 3B's (also members
of `pi_workers`) plus one x86_64 ZimaBoard worker (also a member of
`x86_workers`) — see ADR 0022. Every generic playbook (`health.yml`,
`benchmark.yml`, `onboard.yml`, `swarm-join.yml`) reaches all of `workers`
unchanged; only the two Pi-specific playbooks above are retargeted.

- `playbooks/equip-x86-workers.yml` — the `x86_workers` counterpart to
  `equip-workers.yml` (ADR 0023), not an extension of it (per ADR 0022's own
  Revisit trigger). Same lean venv shape (`uv`, DuckDB CLI, a `redis`/`rq`/
  `duckdb` venv at the same path) but **no `apt` task at all** — this host's
  package state is fragile, and every tool here has a safe user-local
  install already. Also enables `systemd-run --user` linger for this group
  (the one task needing `become: true`), the `x86_workers` equivalent of
  `harden-workers.yml`'s identical Pi-scoped task.

```bash
ansible-playbook -i inventories/local/hosts.yml playbooks/harden-workers.yml --ask-become-pass
ansible-playbook -i inventories/local/hosts.yml playbooks/equip-workers.yml --ask-become-pass
ansible-playbook -i inventories/local/hosts.yml playbooks/equip-x86-workers.yml --ask-become-pass
```

Or via the guarded Makefile targets: `make harden-workers ARGS="--ask-become-pass"`,
`make equip-workers ARGS="--ask-become-pass"`, and
`make equip-x86-workers ARGS="--limit x86-worker-01 --ask-become-pass"`.

RQ/Dask resource limits (`run-rq-burst-worker.yml`,
`run-dask-worker-burst.yml`) are group_vars-parameterized per hardware
class (ADR 0023) rather than hardcoded Pi-sized constants — see
`inventories/example/group_vars/x86_workers.yml` for the overridable vars
and their real, higher values for this hardware class.

```bash
ansible-playbook -i inventories/local/hosts.yml playbooks/onboard.yml
ansible-playbook -i inventories/local/hosts.yml playbooks/onboard.yml --limit workers --ask-become-pass
ansible-playbook -i inventories/local/hosts.yml playbooks/onboard.yml --limit optional_build_nodes

ansible-playbook -i inventories/local/hosts.yml playbooks/swarm-join.yml \
  -e confirm_swarm_join=true --ask-become-pass --limit worker-01
```

Or via the guarded Makefile targets: `make cluster-onboard ARGS="--limit workers --ask-become-pass"`
and `CONFIRM=yes ARGS="--limit worker-01 --ask-become-pass" make cluster-swarm-join`.
