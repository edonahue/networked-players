# Infrastructure

Infrastructure should be reproducible without publishing the identity of the running home environment.

This directory may contain safe Ansible roles, example inventories, generic Swarm stack definitions, health checks, and recovery principles. It must not contain real addresses, hostnames, tunnel configuration, credentials, backup destinations, or production inventories.

Current planned roles:

- one x86 coordination and state host;
- four Raspberry Pi 3B ARM64 workers;
- one optional workstation-class build and analysis node;
- a wired local network with a multi-gigabit backbone and a separate worker fan-out switch.

## Phase-1 starter

This is early scaffolding, not a running cluster. What exists:

- `ansible/` — an `ansible.cfg`, a read-only facts/health playbook (`playbooks/health.yml`),
  and example inventory/group_vars/host_vars to copy into a git-ignored local inventory.
- `swarm/` — a coordination-host `docker-compose.coordination.yml` (Postgres + Redis) for the
  dev loop, plus a Swarm init/join runbook in `swarm/README.md`.

These are verified as configuration only; they have not been run against real hardware.

## Bootstrap checklist (power-on → cluster up)

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
