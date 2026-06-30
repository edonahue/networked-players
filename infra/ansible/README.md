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
ansible.cfg                              defaults; points at the example inventory
playbooks/health.yml                     read-only facts + health checks (Phase 1)
inventories/example/hosts.yml            example hosts (placeholder names)
inventories/example/group_vars/all.yml   example shared variables
inventories/example/host_vars/*.yml      example per-host variables (RFC 5737 addresses)
```

## First run

The `health.yml` playbook is **read-only**: it gathers facts and reports/asserts
architecture, free space, time sync, and SoC temperature, changing nothing. It is safe
to run repeatedly as first contact with new hardware. Mutating baseline roles (service
account, packages, container runtime) come later, each behind its own ADR.

```bash
cd infra/ansible
cp -r inventories/example inventories/local   # then edit with real hosts (git-ignored)
ansible-playbook -i inventories/local/hosts.yml playbooks/health.yml
```
