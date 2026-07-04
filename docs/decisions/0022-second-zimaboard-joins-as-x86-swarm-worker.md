# ADR 0022: The second ZimaBoard joins the Swarm as a dedicated x86_64 worker

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

[ADR 0015](0015-fleet-onboarding.md) classified "a second, stock ZimaBoard 832, no NVMe attached" as `optional_build_nodes` — a standalone box for heavy local work, deliberately kept outside the orchestrated Swarm. Its own Revisit trigger anticipated exactly this moment: "Revisit if the second ZimaBoard's role changes (e.g., it later gets an NVMe and takes on heavier, `coordinators`-adjacent work) — that would be a new decision, not a silent scope change to this one."

The operator has deliberately repurposed that same box as a dedicated Swarm worker rather than a standalone build node. `optional_build_nodes` has no populated hardware right now — no other box fills that role.

Bringing it in surfaced a real technical constraint: `onboard.yml`, `swarm-join.yml`, `harden-workers.yml`, and `equip-workers.yml` all hard-code `hosts: workers`. A host placed in a differently-named group alone would be silently skipped by every one of those plays. At the same time, `harden-workers.yml` and `equip-workers.yml` encode real, confirmed Pi 3B facts that don't hold here — a Broadcom SoC hardware watchdog (this host uses a different watchdog path, like the coordinator's `wdat_wdt`, not confirmed live but known to differ), SD-card write-endurance reasoning for Docker log rotation, and, most importantly, a live `apt: update_cache: true` install task in `equip-workers.yml` — a real host-package operation that must never run against this box, since it previously had Debian testing enabled and ended up with held `libc6`/`libc-bin`/`locales` packages; APT here is deliberately left alone beyond `apt update`.

## Decision

1. **This worker joins the flat `workers` inventory group directly**, alongside the three Pi 3B workers — this is what makes `health.yml`, `benchmark.yml`, `onboard.yml`, and `swarm-join.yml` reach it with zero playbook edits.
2. **Two new, flat (non-nested) groups are added for targeting clarity**: `pi_workers` (the three Pi 3B's) and `x86_workers` (this ZimaBoard). Neither is nested under `workers` via Ansible's `children:` mechanism — `workers` stays a flat `hosts:` list, because `infra/ansible/bootstrap-worker-ssh.sh` reads `ansible-inventory --list`'s `workers.hosts` key directly, which would go empty if `workers` became a parent-only group.
3. **`harden-workers.yml` and `equip-workers.yml` are retargeted from `hosts: workers` to `hosts: pi_workers`** — a two-line change. This makes it structurally impossible for a future fleet operation to accidentally run Pi-specific hardening or the apt-touching baseline-tooling install against a non-Pi worker, rather than relying on an operator remembering a `--limit` exclusion on every invocation.
4. **No new hardening/equip playbook is written for `x86_workers` in this ADR.** This worker only receives the same generic treatment every worker gets (health, benchmark, onboard, guarded Swarm join). A dedicated toolset for non-Pi Swarm workers, if one is ever needed, is a separate, real, not-yet-built task — matching the honest gap `infra/swarm/README.md` already documented for `optional_build_nodes`.
5. **Every safety property ADR 0015/0017 established for joining a worker is unchanged**: explicit operator confirmation (`confirm_swarm_join=true`/`CONFIRM=yes`), one worker at a time (`serial: 1`), no automatic leave, no automatic promotion. This box joined as a worker only.
6. **`optional_build_nodes` is not populated by any other hardware right now.** It stays defined in the example inventory and in `onboard.yml`'s second play as a documented, available role for future hardware — this ADR does not remove that group, only vacates it.

## Consequences

The fleet is now four workers: three Pi 3B's (ARM64, 1GB RAM, `pi_workers`) and one ZimaBoard 832 (x86_64, 8GB RAM, `x86_workers`) — the first architecturally mixed Swarm this project has run. `docs/HARDWARE.md`'s "optional workstation-class build node" row no longer describes real, currently-filled hardware; it's updated to describe this worker's new role instead. Any future non-Pi hardening/tooling need becomes a new, explicit task against `x86_workers`, not an assumed extension of the Pi-scoped playbooks.

## Validation

Live-verified this session: `ansible-inventory --graph` shows the new worker under both `workers` and `x86_workers`, the three Pi's under both `workers` and `pi_workers`; `ansible-playbook --syntax-check` passes for all four retargeted/affected playbooks against the example inventory; `make cluster-health`/`make cluster-benchmark` ran clean both before and after the join (benchmark throughput consistent pre/post-join, no meaningful Swarm-membership overhead observed); `make cluster-onboard` correctly no-op'd the Docker install (already present) and reported readiness; the guarded `make cluster-swarm-join` joined it cleanly; `sudo docker node ls` on the manager confirms the new node `Ready`/`Active` with no `MANAGER STATUS` value; `docker info --format '{{.Swarm.ControlAvailable}}'` on the worker itself reports `false`.

## Revisit trigger

Revisit if this worker ever needs its own hardening/equip pass (e.g., Docker log-rotation tuned for its real storage, or a fuller `uv sync --extra dev` toolset instead of the Pi's lean venv) — that's new `x86_workers`-scoped playbook work, not an extension of `harden-workers.yml`/`equip-workers.yml`. Revisit if `optional_build_nodes` gains real hardware again. Revisit if a fifth worker of a third hardware class joins, which would call for re-examining whether `pi_workers`/`x86_workers` is still the right split or a more general per-architecture grouping is needed.
