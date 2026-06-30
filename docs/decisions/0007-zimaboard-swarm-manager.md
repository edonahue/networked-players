# ADR 0007: Bootstrap the ZimaBoard 832 as the initial Docker Swarm manager

- **Status:** Accepted
- **Date:** 2026-06-30

## Context

`docs/ARCHITECTURE.md` already names a single Docker Swarm manager as the initial orchestration control point, and `docs/HARDWARE.md` names a ZimaBoard 832 as the current x86 coordination host. `infra/swarm/README.md` and `infra/README.md` describe the runbook and bootstrap checklist, but no host had been initialized. A bootstrap session on 2026-06-30 found Docker Engine already installed and running outside Swarm mode, but the eMMC root filesystem at 97% full with no NVMe attached yet, and the operator account not yet in the local `docker` group. Four Raspberry Pi 3B workers are not yet provisioned, and the host has no `python3.12` or `uv` available for the catalog CLI (Debian 11 bullseye ships Python 3.9 only).

## Decision

Initialize Swarm mode on the ZimaBoard now, advertising on its existing LAN interface, and capture the worker join token to local, git-ignored storage immediately, rather than waiting for the Pi workers to exist, so that joining them later is a one-line operation. Treat tonight's scope as bootstrap-only: defer the coordination Postgres/Redis compose stack and any NVMe partitioning/relocation to a follow-up session, since the eMMC root is too constrained to safely pull images or store catalog data tonight. Continue to require `sudo docker` for Swarm operations until the operator's next login picks up `docker` group membership; do not depend on group membership for tonight's bootstrap.

## Consequences

The manager exists and is independently verifiable (`docker info`, `docker node ls`) without depending on worker hardware being ready. The coordination host's local data root (Postgres/Redis volumes, `local/raw`, `local/processed`) remains undecided until the NVMe is attached and relocated off the 28 GB eMMC; until then the host cannot satisfy `docs/DATA_SIZING.md`'s 250 GB ingest floor, and `infra/ansible/playbooks/health.yml`'s free-space assertion is expected to fail honestly against `/` until that relocation happens. No production stack or real join token is committed to this repository; both stay under git-ignored `local/`.

## Validation

`docker info` reports `Swarm: active` and `Is Manager: true` on the coordination host; `docker node ls` lists exactly one manager node; a saved worker join token exists under `local/swarm/` and is excluded from `git status`.

## Revisit trigger

Revisit after the NVMe is attached and `local/`'s effective data root moves off the eMMC (relocation plan, mount point, and a revised free-space floor for the coordination host's Ansible host_vars), after the first Raspberry Pi worker actually joins (confirms the token and `--advertise-addr` choice), or if `enp3s0` is put into service for a separate worker network (would change the `--advertise-addr` reasoning).
