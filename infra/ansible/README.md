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
