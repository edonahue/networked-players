# ADR 0009: Access Portainer via Tailscale instead of an SSH tunnel

- **Status:** Accepted
- **Date:** 2026-07-01

## Context

ADR 0008 deployed Portainer bound to `127.0.0.1`, reachable only via an SSH tunnel, to avoid exposing an admin UI with full `docker.sock` access on the home LAN. In practice, establishing that tunnel from a mobile SSH client (Termius on iOS) was unreliable — port forwarding did not reliably reach the phone's browser. A temporary LAN bind was used once to complete first-login, then reverted, but a permanent LAN bind was rejected: anything joining the home WiFi (an untrusted IoT device, a guest, a compromised laptop) would be able to reach the login page of a tool with effective root-equivalent control over every container on the host. The operator already runs Tailscale on other devices.

## Decision

Bind Portainer to this host's Tailscale IP instead of `127.0.0.1` or the LAN interface, whenever Tailscale is connected. `infra/swarm/deploy-portainer.sh` detects Tailscale automatically (`tailscale ip -4`) and passes it to `docker-compose.portainer.yml` via the `PORTAINER_BIND_IP` environment variable; if Tailscale isn't installed or connected, it falls back to the original loopback-only behavior from ADR 0008 rather than defaulting open. Tailscale itself is installed via `scripts/install-tailscale.sh`, joining this host to the operator's existing tailnet (device authorization is a one-time interactive step: `tailscale up` prints a login URL).

## Consequences

Portainer becomes reachable from any of the operator's tailnet-authorized devices (including a phone, from anywhere, not just the home LAN) without SSH tunneling friction, while remaining unreachable from the LAN, the public internet, or any device that hasn't been explicitly authorized into the tailnet — a stronger and more convenient boundary than either prior option. Tailscale itself becomes a new persistent background service on the coordination host with its own update/authentication lifecycle, distinct from and in addition to the SSH access already in use. This doesn't change ADR 0008's core decision (Portainer as a plain, non-Swarm container, never `0.0.0.0`-bound) — it revises the access-method half of that ADR; the security-boundary reasoning is superseded here, the deployment-primitive reasoning (why not a Swarm service) is not.

## Validation

`tailscale status` on the coordination host shows this device connected to the operator's tailnet; `docker compose -f infra/swarm/docker-compose.portainer.yml ps` shows `portainer` `Up`; `ss -tln | grep 9443` shows the bound address matching `tailscale ip -4`'s output, never `0.0.0.0` and never the LAN IP; a tailnet-joined phone reaches `https://<tailscale-ip>:9443` without any SSH tunnel or port forwarding.

## Revisit trigger

Revisit if Tailscale's own account/billing model changes in a way that's no longer suitable for this project, if the coordination host is ever moved off the operator's personal tailnet (e.g., a shared/multi-operator setup), or if Portainer's `docker.sock` access needs scoping down regardless of network-layer access control.
