# Infrastructure

Infrastructure should be reproducible without publishing the identity of the running home environment.

This directory may contain safe Ansible roles, example inventories, generic Swarm stack definitions, health checks, and recovery principles. It must not contain real addresses, hostnames, tunnel configuration, credentials, backup destinations, or production inventories.

Current planned roles:

- one x86 coordination and state host;
- four Raspberry Pi 3B ARM64 workers;
- one optional workstation-class build and analysis node;
- a wired local network with a multi-gigabit backbone and a separate worker fan-out switch.

Infrastructure is not implemented yet.
