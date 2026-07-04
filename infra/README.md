# Infrastructure

Infrastructure should be reproducible without publishing the identity of the running home environment.

This directory may contain safe Ansible roles, example inventories, generic Swarm stack definitions, health checks, and recovery principles. It must not contain real addresses, hostnames, tunnel configuration, credentials, backup destinations, or production inventories.

Current roles:

- one x86 master/coordination host (Swarm manager, orchestration, authoritative
  dataset storage) — never a worker;
- one dedicated x86_64 Swarm worker (`x86_workers`, ADR 0022/0023) — worker-only,
  never promoted to manager;
- three active Raspberry Pi 3B ARM64 workers (`pi_workers`) — bounded, 1 GB RAM
  each; a fourth Pi and a Pi 3B+ are planned but not yet active (both would join
  `pi_workers` when revived);
- one optional workstation-class build and analysis node;
- a wired local network with a multi-gigabit backbone and a separate worker fan-out switch.

## Current state: a real, live cluster

The Swarm described above is real and running today, not scaffolding — a single-manager
Swarm with the x86 worker and the three active Pi workers all joined and smoke-tested,
recovery-drilled (drain/remove/rejoin), and backed up/restored for real. See
`docs/BUILD_PLAN.md`'s "Where things stand today" section and its status table for the
full, dated evidence trail. What lives in this directory:

- `ansible/` — `ansible.cfg`, the real playbooks (`playbooks/`) this fleet runs
  (health, onboarding, hardening, RQ/Dask fleet work, dataset replication), and
  example inventory/group_vars/host_vars to copy into a git-ignored local inventory
  before pointing any of it at real hosts.
- `swarm/` — the coordination-host `docker-compose.coordination.yml` (Postgres + Redis),
  the read-only catalog-data HTTP layer (ADR 0024), a Swarm init/join runbook in
  `swarm/README.md`, and the jobs-broker/benchmark deployment scripts.

## Original bootstrap sequence (historical reference)

This is how the cluster above was actually brought up from power-on — kept here as a
reference for re-provisioning a node or bringing up a new one (e.g. the planned fourth
Pi or Pi 3B+), not as an implication that the cluster still needs bootstrapping.

1. Flash a **64-bit** OS to each node (aarch64 on the Pis); confirm SSH and a non-root
   service account.
2. Record real hosts/addresses in a git-ignored `ansible/inventories/local/` (copy the
   example); keep secrets in a vault, never in Git.
3. Run the read-only health playbook and resolve any failures (architecture, free space,
   time sync, temperature): `ansible-playbook -i inventories/local/hosts.yml playbooks/health.yml`.
4. Bring up coordination-host services: `docker compose -f swarm/docker-compose.coordination.yml up -d`.
5. Initialize Swarm on the coordination host and join the workers (see `swarm/README.md`);
   verify with `docker node ls` and a global smoke service.
6. Run a first bounded ingestion slice from `docs/OPERATOR_SETUP.md` (`make ingest` with
   `MAX_RELEASES`).
