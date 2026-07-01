# ADR 0010: Bring up the coordination Postgres/Redis stack ahead of the NVMe

- **Status:** Accepted
- **Date:** 2026-07-01

## Context

ADR 0007 bootstrapped the ZimaBoard 832 as the Docker Swarm manager and explicitly deferred `infra/swarm/docker-compose.coordination.yml` (Postgres 17 + Redis 7-alpine) because the eMMC was at 97% full (817 MB free) with no NVMe attached, and pulling images or writing data volumes in that state was judged unsafe. As of this session, the NVMe is still not attached, but the eMMC's real free space has recovered substantially — `df` reported roughly 11.5 GB free immediately before this stack came up. Separately, `docs/DATA_SIZING.md`'s ~250 GB floor is scoped to a full bulk Discogs dump parse (Milestone 3), not to two lightweight, bounded, healthchecked containers. Only `infra/swarm/.env.example` (placeholder values) had existed until now; the stack had never actually run.

## Decision

Bring up `docker-compose.coordination.yml` now, via a new idempotent `infra/swarm/deploy-coordination.sh` that generates a real `.env` on first run (random password via `openssl rand -base64 24`, chmod 600, git-ignored) rather than waiting for the NVMe. This narrows what "the storage blocker" gates going forward: the 250 GB bulk-ingest floor still blocks Milestone 3, but not standing up Postgres/Redis for local development. The compose file's own design is unchanged (loopback-bound, named volumes, healthchecks) — this ADR only revises the timing/sequencing half of ADR 0007's deferral, not the Swarm-manager bootstrap or the NVMe-partitioning deferral itself.

## Consequences

Milestone 4 and later milestones gain a real place to put structured state ahead of schedule. The eMMC now carries live, restart-persistent `postgres-data`/`redis-data` volumes that must be migrated (not simply recreated) onto the NVMe once it's attached, or accumulated state is lost. Available eMMC headroom shrinks further; any future work pulling images or writing data on this host should re-check free space rather than assume ~11.5 GB still holds. No new network exposure is introduced — both services remain loopback-bound only, confirmed via `ss -tln` (`127.0.0.1:5432`, `127.0.0.1:6379`, never `0.0.0.0`). This does not make the host ingestion-ready: `scripts/check-ingest-feasibility.sh`'s 250 GB floor is unchanged.

## Validation

`docker compose -f infra/swarm/docker-compose.coordination.yml ps` shows both `postgres` and `redis` `Up (healthy)` — confirmed. `ss -tln` shows `127.0.0.1` only for ports 5432 and 6379 — confirmed. `git check-ignore -v infra/swarm/.env` confirms `.env` is excluded from version control — confirmed (`.gitignore:30:.env`).

## Revisit trigger

Revisit once the NVMe is attached and ADR 0007's own revisit trigger fires: at that point, migrate the `postgres-data`/`redis-data` volumes (not recreate them) onto the new mount and update the coordination host's Ansible free-space floor. Revisit sooner if eMMC free space drops back toward the original ADR 0007 floor before the NVMe lands — that would mean pausing this decision (stopping the stack), not living with it.
