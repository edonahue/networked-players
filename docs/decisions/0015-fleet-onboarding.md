# ADR 0015: Fleet onboarding tooling for Pi workers and a second ZimaBoard

- **Status:** Accepted
- **Date:** 2026-07-01

> **Amended by [ADR 0017](0017-guarded-swarm-worker-join-automation.md)
> (2026-07-02):** the "actual `docker swarm join` stays a manual, printed
> command" clause in Decision 3 below is narrowed, not reversed — a guarded,
> explicitly-confirmed, one-worker-at-a-time playbook now runs the join
> itself, but every safety property this ADR cared about (explicit operator
> action per node, no automated topology change without confirmation) is
> preserved. See ADR 0017 for the reasoning.

> **Amended by [ADR 0022](0022-second-zimaboard-joins-as-x86-swarm-worker.md)
> (2026-07-03):** Decision 1 below is reversed for this specific box — the
> second ZimaBoard is no longer `optional_build_nodes`; it has joined the
> Swarm as a dedicated `x86_workers` worker. `optional_build_nodes` stays
> defined for any future hardware that fills that role, but nothing
> populates it right now. See ADR 0022 for the reasoning and the inventory
> restructuring it required.

## Context

The operator has the four planned Raspberry Pi 3B workers ready to provision, plus a
second ZimaBoard 832 (stock, no NVMe attached) they want to bring into the fleet.
Nothing in the repo automated any of this yet: `infra/ansible/` had only `health.yml`
(read-only checks, ADR-none) and `harden.yml` (coordinator-only config,
[ADR 0014](0014-coordination-host-hardening.md)) — no onboarding/bootstrap playbook
existed, and joining a worker to the Swarm was a fully manual step
(`infra/swarm/README.md`'s runbook: SSH to each Pi, paste a token by hand). The
inventory had already anticipated this moment, though:
`infra/ansible/inventories/example/hosts.yml` has defined `coordinators`, `workers`,
and `optional_build_nodes` groups since early in the project, just never populated
with real hosts or given their own `group_vars`.

Two things confirmed via research before deciding, not assumed:
- No `group_vars` existed yet for `workers` or `optional_build_nodes` — only
  `coordinator`-specific `host_vars`.
- `infra/swarm/init-swarm-manager.sh` already captures the real Swarm join token to
  `local/swarm/worker-join-token.txt` and a ready-to-paste
  `local/swarm/worker-join-command.txt` (git-ignored, chmod 600) — this file lives on
  the coordination host, the same host any onboarding playbook runs from, so it can
  be read directly rather than asking the operator to hunt it down.

## Decision

1. **The second ZimaBoard joins as `optional_build_nodes`, not `workers`.** This
   matches `docs/HARDWARE.md`'s existing "workstation-class build node... must not
   become required for public availability" concept exactly, and is a materially
   different role than the ARM64, 1GB-RAM Pi workers: real x86_64 compute, but kept
   outside the orchestrated Swarm entirely. It does not join the cluster — it's a
   standalone box the operator uses directly for heavy local work (builds,
   benchmarks, expensive analysis), the same category `docs/HARDWARE.md` already
   named before any specific hardware filled that role. No storage commitment is made
   now; it can get its own NVMe later if a real workload justifies it, the same
   sequencing the first ZimaBoard went through
   ([ADR 0013](0013-nvme-storage-layout.md)).
2. **`infra/ansible/playbooks/onboard.yml` is a single file with two plays**, so a
   full run onboards everyone, or `--limit workers` / `--limit optional_build_nodes`
   targets one group:
   - `hosts: workers` — installs Docker Engine idempotently (the same vendor
     convenience-script pattern `scripts/install-tailscale.sh` already uses:
     `curl -fsSL https://get.docker.com | sudo sh`, a no-op if `docker` is already on
     PATH), adds the Ansible user to the `docker` group, and reports readiness
     including the literal `docker swarm join` command (read via
     `lookup('file', ...)` against `local/swarm/worker-join-command.txt`).
   - `hosts: optional_build_nodes` — verifies Docker is already present (it has
     CasaOS, like the first ZimaBoard, so Docker ships with it) rather than
     installing it, and reports readiness. No Swarm-related tasks at all.
3. **The playbook prepares and verifies; the actual `docker swarm join` stays a
   manual, printed command**, not something Ansible executes. This continues the
   standing convention established across ADR 0010/0013/0014: Ansible handles safe,
   reversible host configuration, while anything that changes real cluster topology
   (adding a node to the Swarm) is an explicit, operator-run step they see and
   confirm before it happens. This is a bigger blast-radius category than host-local
   config — a bad join can't be undone by re-running a playbook the way a bad
   `sysctl` value can.
4. **`onboard.yml` doesn't duplicate `health.yml`'s checks.** `health.yml` already
   asserts 64-bit architecture and a free-space floor for `hosts: all`; the new
   playbook is meant to run *after* `health.yml` confirms a node is reachable and
   healthy, not to re-verify the same facts.

## Consequences

Onboarding tooling now exists, but no physical node has actually been onboarded by
this ADR — `docs/BUILD_PLAN.md`'s Milestone 2 Pi tasks stay unchecked, since the
repository has no evidence any Pi has joined yet (per `AGENTS.md`'s rule against
claiming something exists before there's evidence for it). The real (git-ignored)
`infra/ansible/inventories/local/hosts.yml` is left for the operator to extend
themselves when hardware is reachable — it already has a clear inline comment
describing how to add a `workers:` group, and needed no repository change to do that.
`optional_build_nodes` now has a real, if not-yet-materialized, host in the operator's
possession — `docs/HARDWARE.md` records this as a known, reported fact, the same
epistemic footing as every other hardware entry in that table (operator-reported, not
independently verified by tooling).

## Validation

`ansible-playbook --syntax-check onboard.yml` against the example inventory (the only
inventory with `workers`/`optional_build_nodes` hosts populated) passes;
`lookup('file', 'local/swarm/worker-join-command.txt')` fails with a clear, expected
error when that file doesn't exist yet (true for this host today, since no Pi has
triggered token capture) rather than a cryptic one; `make check` passes (no Python
code touched).

## Revisit trigger

Revisit once the first Pi worker actually joins — confirms the printed join command
and the Docker-install path work end to end on real ARM64 hardware, not just in
`--syntax-check`. Revisit if the second ZimaBoard's role changes (e.g., it later gets
an NVMe and takes on heavier, `coordinators`-adjacent work) — that would be a new
decision, not a silent scope change to this one. Revisit if a fifth or later worker
class is added that isn't a Pi 3B (a different resource-constraint profile than
`docs/HARDWARE.md` currently documents).
