# ADR 0008: Add Portainer CE for Swarm visibility, deferring metrics tooling

- **Status:** Accepted
- **Date:** 2026-07-01

## Context

ADR 0007 bootstrapped the ZimaBoard 832 as the initial Docker Swarm manager but added no visibility tooling — the operator's only view into the cluster is raw `docker`/`docker service`/`docker node` CLI output. No monitoring or observability platform (Portainer, Grafana, Prometheus, cAdvisor) is named anywhere in the repo; a full documentation review confirmed this is a genuinely open decision, not a deferred placeholder. The cluster currently has one manager node and zero workers, so there is no multi-node metrics data yet worth graphing.

## Decision

Add Portainer CE only, as a plain `docker compose` container on the coordination host's existing Docker Engine — not a `docker service create`. Docker Swarm's `--publish` always binds `0.0.0.0` regardless of mode, which is unacceptable for an unauthenticated-until-first-login admin UI with full `docker.sock` access on a home LAN. A plain compose container supports binding to `127.0.0.1` explicitly, matching the pattern `docker-compose.coordination.yml` already uses for Postgres/Redis. Access is via SSH tunnel only; Portainer is never bound to the LAN interface or exposed publicly. Explicitly defer Prometheus, Grafana, and cAdvisor until Raspberry Pi workers actually join the Swarm and there is real multi-node load worth graphing.

## Consequences

The operator gains a web UI for Swarm nodes, services, stacks, and container state without adding a metrics collection/storage/dashboard pipeline. Portainer itself becomes a new persistent component with `docker.sock` access — effectively full control over every container and the Swarm — so its exposure surface (loopback-only bind, SSH-tunnel-only access, no LAN/public port) is the primary mitigating control and must be preserved if this compose file is ever changed. Portainer's own state (users, settings, TLS certificate) lives in a named Docker volume rather than a bind mount, since the coordination host's real data root remains undecided pending NVMe relocation (ADR 0007).

## Validation

`docker compose -f infra/swarm/docker-compose.portainer.yml ps` shows the `portainer` container `Up`; `ss -tln | grep 9443` shows `127.0.0.1:9443` only, never `0.0.0.0:9443`; an SSH tunnel followed by a browser to `https://127.0.0.1:9443` reaches the Portainer login/init screen, and after setting the admin password the dashboard reports the local Docker environment with Swarm active and one manager node.

## Revisit trigger

Revisit once the first Raspberry Pi worker actually joins the Swarm (multi-node data becomes worth graphing, motivating Prometheus/Grafana/cAdvisor), or if Portainer's direct `docker.sock` access ever needs to be scoped down (for example, via a socket proxy that limits which API endpoints it can reach).
