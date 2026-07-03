# ADR 0017: Guarded, repeatable Swarm worker join automation

- **Status:** Accepted
- **Date:** 2026-07-02

## Context

[ADR 0015](0015-fleet-onboarding.md) deliberately kept `docker swarm join`
manual: "the playbook prepares and verifies; the actual `docker swarm join`
stays a manual, printed command, not something Ansible executes... a bad
join can't be undone by re-running a playbook the way a bad `sysctl` value
can." That reasoning was sound at the time and still holds for the
*topology-changing* risk itself.

Two real constraints changed the calculus for *how* that manual step gets
run, without changing whether an operator explicitly triggers it each time:

1. The operator drives this host from Termius on an iPhone — typing a
   multi-flag `docker swarm join --advertise-addr ... --token ... host:2377`
   command by hand, three times, with no copy-paste-safe token file open at
   the same time, is exactly the kind of typo-prone manual step this
   project's existing guarded scripts (`backup-swarm-manager-state.sh`,
   `restore-swarm-manager-state.sh`) already exist to avoid for other
   Swarm-adjacent operations.
2. A fourth Pi worker is expected to join later, using the same procedure —
   this needs to be genuinely repeatable, not a one-off manual sequence
   remembered from this session.

Confirmed via this session's live inspection, not assumed: the coordinator
has no `docker` group membership and no passwordless/TTY-less sudo, so
every Docker-touching command in this repo — including any join automation
— still has to be triggered by the operator's own invocation with
`--ask-become-pass`; nothing here becomes unattended.

## Decision

Add `infra/ansible/playbooks/swarm-join.yml`, narrowing (not reversing)
ADR 0015's manual-join clause:

1. **Still explicitly operator-triggered, one worker at a time.** `serial:
   1`, and the operator invokes it with `--limit <one-worker>` — never a
   bare run against the whole `workers` group. This preserves the same
   "operator sees and confirms each join" property ADR 0015 was protecting,
   it just removes the risk of a hand-typed command with an embedded secret
   token on a phone keyboard.
2. **Requires an explicit `confirm_swarm_join=true` extra-var**, asserted
   at the top of the play with a clear failure message otherwise — the
   guarded-script pattern already established by
   `restore-swarm-manager-state.sh`'s `--yes-i-am-sure` flag, adapted to
   Ansible's own confirmation idiom.
3. **Checks the target's own Swarm state before doing anything.** Already
   `active` → reports a no-op and stops for that host; never calls `docker
   swarm leave` automatically under any circumstance, and never promotes a
   node to manager (no such task exists in the playbook at all).
4. **Token handling uses `no_log: true`** on the fact-gathering and join
   tasks specifically, so the worker join token never appears in Ansible's
   own stdout or logs, on top of the token file itself already being
   git-ignored and `chmod 600`.
5. **Uses each worker's Ethernet address explicitly** for both
   `--advertise-addr` and `--data-path-addr` (via `swarm_advertise_addr`/
   `swarm_data_path_addr`, defaulting to `ansible_host`) — never lets
   Docker auto-select an interface, which matters on any worker with more
   than one active network path.
6. **Verification stays split across two steps, deliberately.** The
   playbook only confirms the *worker's own* local Swarm state went
   `active` after joining — it does not attempt a delegate-to-manager
   cross-check inside the same run (that would need the *coordinator's*
   sudo password reused under the same `--ask-become-pass` invocation as
   the worker's, which is a real risk if those passwords ever diverge, even
   though they're confirmed equal today). The manager-side confirmation
   (`docker node ls` showing Ready/Active, correct cluster) stays a
   separate, plain operator one-liner — its own gated phase, not folded in.

## Consequences

Joining a worker becomes a single pasteable command
(`CONFIRM=yes ARGS="--limit worker-01 --ask-become-pass" make
cluster-swarm-join`) instead of a hand-typed multi-flag Docker command with
an embedded token, while every safety property ADR 0015 cared about —
explicit operator action per node, no silent topology change, no
auto-promotion, no auto-leave — is preserved or made stricter (the no-op
and different-cluster-refusal behavior is new, not present in the fully
manual version at all). This does not change ADR 0015's Docker-install or
onboarding logic, which stays as-is.

The playbook cannot yet prove *for itself* that the manager agrees the join
succeeded — that's an intentional gap, covered by Phase 8 of the guided
bring-up (`sudo docker node ls`), not a missing feature.

## Validation

`ansible-playbook --syntax-check` against the example inventory (only
inventory with synthetic `workers` hosts populated) passes. Live validation
(a real join, a real no-op re-run against an already-active worker, and a
real manager-side `docker node ls` confirmation) happened as part of this
session's guided three-worker bring-up — see `docs/BUILD_PLAN.md`
Milestone 2 for the dated real-run evidence.

## Revisit trigger

Revisit if the coordinator ever gains passwordless sudo or `docker` group
membership (the delegate-to-manager cross-check deferred in Decision 6
becomes safe to add directly into this playbook). Revisit when the fourth
Pi worker joins — confirms this playbook is genuinely reusable unchanged,
not just correct for three specific nodes. Revisit if a second Swarm
manager is ever added, the same trigger ADR 0016 already names for its own
scope.
