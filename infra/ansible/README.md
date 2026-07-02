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
playbooks/harden.yml                               coordinator hardening, state-changing (ADR 0014)
playbooks/onboard.yml                              Pi worker + build-node onboarding (ADR 0015)
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
