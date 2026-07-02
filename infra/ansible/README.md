# Ansible

Ansible is planned to provide repeatable baseline configuration for the coordination host and four worker nodes.

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
files/benchmark_parse.py                          standalone probe copied to each node by benchmark.yml
run-health-local.sh, run-benchmark-local.sh       guarded local entry points (share run-playbook-local.sh)
inventories/example/hosts.yml                     example hosts (placeholder names)
inventories/example/group_vars/all.yml            example shared variables
inventories/example/group_vars/workers.yml        example Pi 3B worker variables
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
`ansible-core` via `uv tool install` if it isn't already on `PATH`.

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

Real result on the coordination host (x86_64, 4 CPUs), 2026-07-02: 20,000
iterations (40,000 releases parsed) in ~2.7s, ~14,600 releases/sec, ~14MB
peak RSS. No Pi or second-ZimaBoard numbers exist yet — see
`docs/HARDWARE.md`'s "Measured capability" section, to be filled in once
that hardware is reachable.

## Mutating playbooks

Two playbooks actually change state, each behind its own ADR — treat them as a
different risk category than the read-only `health.yml`:

- `playbooks/harden.yml` ([ADR 0014](../../docs/decisions/0014-coordination-host-hardening.md)):
  `hosts: coordinators` only — persistent journald, hardware watchdog, Docker log
  rotation, swappiness tuning.
- `playbooks/onboard.yml` ([ADR 0015](../../docs/decisions/0015-fleet-onboarding.md)):
  onboards the `workers` group (installs Docker, prints the real `docker swarm join`
  command) and the `optional_build_nodes` group (verifies Docker is present). Run
  *after* `health.yml` confirms a node is reachable and healthy. Prepares and
  verifies only — the actual Swarm join stays a manual, operator-run command; see
  `infra/swarm/README.md`'s runbook.

```bash
ansible-playbook -i inventories/local/hosts.yml playbooks/onboard.yml
ansible-playbook -i inventories/local/hosts.yml playbooks/onboard.yml --limit workers
ansible-playbook -i inventories/local/hosts.yml playbooks/onboard.yml --limit optional_build_nodes
```
