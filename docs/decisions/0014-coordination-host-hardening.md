# ADR 0014: Coordination host hardening for long-running background jobs

- **Status:** Accepted
- **Date:** 2026-07-01

## Context

The ZimaBoard 832 coordination host crashed and required a manual reboot during this
session. Investigating turned up two real findings, not assumptions:

1. **No forensic trail exists.** `journalctl --list-boots` and `dmesg` both fail for a
   non-root user, and `/var/log/journal` doesn't exist — journald runs in volatile mode
   (`/run/log/journal`, tmpfs), wiped on every reboot. Whatever caused the crash is gone.
2. **The timeline doesn't cleanly support "the earlier heavy parse job's CPU load caused
   an immediate crash."** That job (a partial full-scale run of `parse-releases`,
   recorded in `docs/DATA_SIZING.md`'s "Partial full-scale run") finished around 14:39;
   the crash (per `last -x`) happened at 14:57, 18 minutes later, during comparatively
   light work. A delayed thermal effect on this host's low-power Intel Celeron J3455
   (Apollo Lake, ~10W TDP, a thermally sensitive CPU class under sustained load) is
   plausible but not confirmed, and won't be confirmable for this specific incident
   either way — the logs that would show it don't exist.

Separately, the operator wants to prepare for pulling and processing the full latest
monthly Discogs dataset, including eventually exploring parallelism in the download and
parse steps. `packages/catalog`'s parser is currently single-process by design
(`docs/ARCHITECTURE.md`: "The parser itself is initially single-process"), and the one
real full-scale data point available (`docs/DATA_SIZING.md`'s partial run: ~428.5
releases/sec, single core, ~167.6MB peak RSS) gives no information about *where* time is
actually spent — decompression, XML tokenization, Python object construction, or Parquet
writing. Designing a parallel parser without that data would be optimizing a guess.

A genuinely useful find during this investigation: the host has an **unused hardware
watchdog** (`/dev/watchdog`, `/dev/watchdog0`; the `wdat_wdt` kernel module is already
loaded) that systemd isn't arming. This is a direct, low-effort mechanism for automatic
recovery from a hang, independent of diagnosing what caused any specific past incident.

## Decision

1. **Harden the host now, independent of confirming this specific crash's cause.** The
   forensic-trail gap and the unused watchdog are real, actionable gaps regardless of
   what actually happened on 2026-07-01.
2. **Introduce `infra/ansible/playbooks/harden.yml`** — a new playbook, targeted at the
   `coordinators` inventory group only (the Pi workers aren't provisioned yet; their own
   hardening, scoped to a 1GB-RAM-constrained profile, is a distinct future decision, not
   bundled here). This is a real precedent shift worth naming explicitly:
   `infra/ansible/playbooks/health.yml` is deliberately read-only ("gathers facts and
   reports/asserts, but changes nothing"); `harden.yml` is this project's first Ansible
   playbook that actually applies configuration. It stays idempotent and each task states
   what it verifies/changes, matching the project's existing rigor, but the risk category
   is different from `health.yml` and should be treated as such by future readers.
3. **Four concrete changes in `harden.yml`:** persistent journald storage (the
   forensic-trail fix); an armed hardware watchdog (`RuntimeWatchdogSec`, confirmed most
   reliably via a deliberate, operator-timed reboot, not forced by the playbook itself);
   Docker log rotation (prevents unbounded log growth from long-lived containers); lower
   `vm.swappiness` (protects latency-sensitive services like Postgres/Redis/SSH from
   being swapped out during a long batch job, given ample free RAM either way).
   `live-restore: true` was tried and reverted: confirmed live that it's a hard,
   documented incompatibility with Docker Swarm mode (this host has Swarm active per
   ADR 0007) — `dockerd` failed to start entirely with it set, taking
   Postgres/Redis/Portainer down until fixed. Not revisited unless Swarm mode itself is
   ever dropped from this host.
4. **Heavy jobs run under `systemd-run`** (`scripts/run-ingest-supervised.sh`) instead of
   a bare backgrounded shell process — survives session/SSH disconnects, gets real cgroup
   resource accounting (`Nice`, I/O scheduling class, a generous `MemoryMax` safety
   ceiling), and once persistent journald exists, durable logging independent of any
   scratch file tied to a particular tool session.
5. **Profile before parallelizing.** A short, real `cProfile` run against the
   already-downloaded June 2026 releases dump (bounded to ~50,000 releases, minutes not
   hours) establishes where time actually goes before any parallel-parser redesign is
   scoped. The redesign itself — whether that means file-splitting for true parallel
   decompression/tokenization, or a producer/consumer worker pool for the Python-side
   transform/write stage — is **explicitly deferred** to a follow-up decision once real
   profiling data exists, not designed against a guess now.
6. **Parallelize the four dump-kind downloads** (`scripts/download-all-kinds.sh`) as a
   separate, lower-risk, immediately-available win: releases/artists/labels/masters are
   independent objects with no interdependency, so concurrent `download --kind X`
   invocations remove artificial sequential wait time — while stating plainly that
   network bandwidth may still be the real ceiling, not oversold as a guaranteed speedup.

## Consequences

Future incidents on this host become diagnosable (persistent journald) and, for a class
of hang/freeze failures, self-recovering (armed watchdog) — without having confirmed
what caused this specific crash, since that evidence no longer exists. Docker's
already-running containers (Postgres/Redis/Portainer) do **not** retroactively gain log
rotation from this change — only newly created containers do; recreating them (via their
existing `deploy-coordination.sh`/`deploy-portainer.sh` scripts) to pick up rotation
retroactively is a real, deliberate follow-up, not automated here. `infra/ansible/`
now has two playbooks with meaningfully different risk profiles (`health.yml` read-only,
`harden.yml` state-changing) — future playbooks should state which category they belong
to as clearly as these two do. No parallel-parser code exists yet; this ADR sets up the
measurement step that decides whether and how to build one, not the parallelism itself.

**A real, confirmed gap found while applying this ADR, not a hypothetical:** after the
`live-restore` misstep (above) took `dockerd` down and it was restarted via
`systemctl restart docker`, the coordination stack and Portainer containers — all
defined with `restart: unless-stopped` — did **not** come back up automatically. They
were left in a clean `Exited` state (Postgres/Redis exit code 0, Portainer exit code
2) rather than being restarted by the daemon on its own. Recovery required manually
re-running `deploy-coordination.sh`/`deploy-portainer.sh` (idempotent, safe — they
recognized the existing stopped containers and started them without recreating).
**Don't assume `unless-stopped` alone makes this host self-healing after a Docker
daemon restart** — the actual, confirmed recovery path is re-running the deploy
scripts. Root cause not investigated further here (out of scope for this pass); worth
revisiting if it recurs.

A second real consequence of the same `live-restore` failure: because Ansible handlers
run in notification order and a failed handler stops the rest for that host, the
`Restart docker` handler's failure meant the later-notified `Reload sysctl` handler
never ran in that pass — the swappiness *file* was written correctly by its task, but
`vm.swappiness` stayed at the default `60` at runtime until `sudo sysctl --system` was
run by hand. A bare playbook re-run would **not** have fixed this on its own either:
once the file already matches, its task reports `ok` rather than `changed`, so it
wouldn't re-notify the handler. Independent hardening changes probably shouldn't be
coupled this way — a future revision of `harden.yml` could apply each change's effect
within its own task (e.g. `ansible.builtin.command: sysctl --system` immediately
after writing the file, not via a deferred handler) rather than relying on
handler-notification order across unrelated changes. Not restructured in this pass;
noted for the next time this playbook is touched.

## Validation

`journalctl --list-boots` succeeds and lists more than the current boot after a
deliberate reboot; `systemctl show | grep Watchdog` reports a non-zero
`RuntimeWatchdogUSec` (armed) after that same reboot; `docker info` reports the
configured logging driver/opts and `Live Restore Enabled: false` (deliberate, see
Decision above); `sysctl vm.swappiness` reports `10`;
`scripts/run-ingest-supervised.sh` run against the
short profiling job (Step 5) completes cleanly and is visible via
`journalctl -u <unit>`, confirming the supervised pattern works before trusting it for
a real multi-hour run.

## Revisit trigger

Revisit once the Raspberry Pi workers are provisioned — they'll need their own hardening
pass, scoped to their 1GB RAM constraint, likely a different `harden.yml` task set or a
separate playbook rather than extending this one's `coordinators`-only scope.

**Step 5's profiling happened the same day** (see `docs/DATA_SIZING.md`'s "Real
profiling" section) and produced a real, decisive finding: the bottleneck was neither
decompression nor Parquet writing (both expected-but-wrong guesses) but 3.95 million
repeated `lxml` `findtext()` calls in `_text()` — 54% of total time. That was fixed as
a same-day algorithmic change (`_child_text_map`, ~1.9x measured speedup), explicitly
*not* a parallel-parser redesign. Multiprocess parallelism (the original open question
this ADR deferred) remains genuinely undecided — revisit it as its own decision if the
now-revised ~5.2 hour full-parse estimate is still too slow for the intended cadence,
informed by this same real profiling data rather than a fresh guess.

Revisit if a future incident occurs with the hardening in place — the persistent logs
and watchdog behavior from that incident are real signal this ADR's assumptions should
be checked against.

**The multiprocess-parallelism question above is closed for now, with a real result.**
The full unbounded parse this ADR's hardening was built for ran to completion the same
night: 2026-07-01 17:59:48 EDT → 2026-07-02 00:02:49 EDT, 6h 3m elapsed, 19,192,301
releases at ~881 releases/sec average, `validate` clean at full scale (see
`docs/DATA_SIZING.md`'s "Full unbounded run: complete" and `docs/BUILD_PLAN.md`
Milestone 3). That's close to the ~5.2 hour profiling-based estimate above (real
wall-clock runs a bit longer than a pure-CPU extrapolation, since it also carries I/O
and the monitor unit's own overhead) and confirms the hardened supervised pattern —
watchdog, persistent journald, resource-bounded `systemd-run`, ntfy notifications —
held up cleanly for a genuine multi-hour unattended job with no incident. Multiprocess
parallelism remains undeployed; nothing in this run's real numbers currently makes a
~6 hour monthly cadence feel too slow to justify that added complexity, so it stays a
deferred, not urgent, decision.
