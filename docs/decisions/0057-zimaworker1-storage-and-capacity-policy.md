# ADR 0057: zimaworker1 gets an explicit storage/capacity policy after a real disk-full incident

- **Status:** Accepted
- **Date:** 2026-08-04

## Context

A real `cohort.score` dispatch to zimaworker1 (the x86_64 capability-platform
worker, ADR 0022/0034) found the host at 100% disk usage — 0 bytes free —
breaking basic Ansible connectivity. Emergency, authorized cleanup (generic
caches, a stale dataset replica) recovered enough space to get further, but
the run then hit a DuckDB temp-space ceiling.

A read-only investigation (repo code/ADRs plus direct, non-destructive
inspection of the live host) found the real story is structural, not "one
dataset grew too big": the Networked Players dataset cache
(`discogs` + `discogs-onehop`, 8.8G) is less than half of what was actually
consuming the disk. `/var/log` (3.9G journal + 735M `syslog` + 735M
`daemon.log`, undiagnosed at investigation time) was nearly as large.
`/home/casaos` (3.6G) is the CasaOS NAS software's own app data — this
ZimaBoard, like the coordination host, runs CasaOS as its base OS, so this
27.7G eMMC partition has always had two independent tenants sharing it with
no governance between them.

Two distinct problems, previously conflated as one incident:

1. **Why the disk hit 0 bytes free**: unbounded accumulation across several
   independent, undocumented growth paths on a single partition with no
   size governance anywhere — `replicate-dataset-x86.yml` has no
   max-total-bytes guard (by design, unlike the Pi playbook's 2GiB cap, so
   dataset snapshots only ever accumulate); `deploy-platform-runtime.yml`
   never pruned old release bundles; `/var/log` grew past its rotation
   cadence; CasaOS's own footprint grows independently. ADR 0022's own
   Revisit trigger named part of this in advance ("Docker log-rotation
   tuned for its real storage") and was never acted on.
2. **Why `cohort.score` then failed with a DuckDB out-of-memory-class error
   even after partial cleanup (down to ~1.1G free)**: a narrower, separate
   software gap. ADR 0033 already measured and bounded this workload's RAM
   (worst seed ~1.5GB RSS at `--memory-limit 2GB`), and it already
   succeeded on this exact host on 2026-07-09. What was never bounded is
   DuckDB's own spill directory: `graph.py`'s `CreditGraph.open()` set
   `memory_limit`/`threads`/`temp_directory` but never
   `max_temp_directory_size`, so DuckDB's spill ceiling implicitly tracked
   whatever free disk happened to exist at connect time — at ~1.1G free,
   that ceiling was too small for a worst-case seed's spill needs.

## Decision

**Dataset**: `discogs-onehop` (2.2G) is required — `submit_cohort_score.py`
and `research.graph-metrics` both name only this dataset; a repo-wide grep
for `DatasetIdentity(name="discogs"` (the full replica) returns zero
matches in any registered workload or submission script. The full
`discogs` replica (6.6G) was fetched via the official checksummed path on
2026-07-04 (`.verified.json` present, dated with ADR 0025's own creation),
genuinely deliberate at the time, but superseded five days later by ADR
0033's one-hop-only reach-scoring redesign — historical, not currently
required by any live workload, and cheaply reproducible on demand via the
same `replicate-dataset-x86.yml` path against the coordination host's
authoritative copy (ADR 0013) if ever needed again. Removed with explicit
operator sign-off (see Validation).

**DuckDB scratch is now explicitly bounded, not implicit.**
`CreditGraph.open()` gained a `max_temp_directory_size` parameter (unset by
default — every existing caller's behavior is unchanged); `cohort.score`'s
platform path (worker handler → `submit_cohort_score.py`'s new
`--max-temp-directory-size`, default `3GB`) sets it explicitly. This
matters beyond just fixing this incident: without a ceiling, a single heavy
query could in principle spill until a *shared* disk hits zero bytes free,
degrading CasaOS's own operation on the same filesystem, not just failing
its own job.

**Release bundles are now pruned.** `deploy-platform-runtime.yml` never
deleted old versioned releases under `platform_release_root`. Added a
keep-last-N (default 3, i.e. this deploy plus 2 prior for rollback
headroom) prune step using `ansible.builtin.find` + `sort(attribute='mtime')`,
excluding the release just deployed.

**The existing health-check floor was silently too low to catch this.**
`playbooks/health.yml`'s `min_free_gb` floor already existed
(ADR 0013's own precedent) but `x86_workers` inherited the generic
`min_free_gb: 1` — a floor low enough to report "healthy" at exactly the
kind of margin that just broke a real job. Raised to `min_free_gb: 6` for
`x86_workers` specifically (margin above `cohort.score`'s 3G DuckDB
ceiling), in both the real local inventory and the example inventory's
guidance (which previously told operators *not* to override this for the
`workers` group as a whole — narrowed to explain the Pi-specific reasoning
doesn't hold for x86 workers).

**A read-only free-space preflight runs before every dispatch.** Added
`require_free_disk()` to `_platform_client.py` (shared by all three
submission scripts), using the same `df`-based method as `health.yml`'s own
floor check, invoked ad hoc via the existing `ansible()` helper — no new
dependency. Refuses to submit rather than dispatching into a worker that's
already too tight on disk. Deliberately a smaller, per-dispatch floor
(2G for `cohort.score`/`research.*`, 0.5G for the KB-scale
`artifact.validate` fan-out) than the broader 6G health-check floor: this
preflight only protects against dispatching into an already-bad situation,
it does not replace the health check's broader "is this host
well-provisioned" signal.

**`/home/casaos` is explicitly out of scope.** It is the operator's own
NAS application data, unrelated to Networked Players, sharing this eMMC
only because this ZimaBoard runs CasaOS as its base OS. No decision here
manages, prunes, or budgets against it — any future storage budget for
this host must simply account for it as a real, independently-growing
consumer this project does not control.

**No hardware change is required to unblock `cohort.score`.** Software
remediation (dataset removal, log cleanup, the DuckDB ceiling) plausibly
recovers most of the 27.7G disk, and the same workload already succeeded on
this exact hardware once before at far less headroom than that. A small
dedicated data drive (reusing ADR 0013's proven `/mnt/data` pattern —
external drive, ext4, bind-mounted onto `local/`) remains a reasonable
optional follow-up if margin is still tight after remediation, permanently
separating this project's footprint from CasaOS's own — not committed to
here.

## Consequences

`CreditGraph.open()`'s new parameter is opt-in and additive — no behavior
change for any of the ~150 existing call sites that don't pass it.
`cohort.score` submissions now have a predictable worst-case disk
footprint instead of an implicit one tied to ambient free space.
Submission scripts gained one more required round-trip (the preflight) per
dispatch — a few hundred milliseconds of `df` over SSH, not a measurable
cost against jobs that run for minutes. The `min_free_gb` floor change
means `make cluster-health` now correctly reports zimaworker1 unhealthy at
its current real free space until the remediation below completes — this
is the guard doing its job, confirmed live (see Validation).

**Not yet closed by this ADR at time of writing**: `/var/log`'s exact spam
source (needs root log access, gated on operator action); the full
`discogs` replica's actual removal (gated on explicit operator sign-off);
a real end-to-end `cohort.score` dispatch proving the fix against the real
failure mode. This ADR's mechanism/policy decisions (dataset call,
DuckDB ceiling, release pruning, health floor, preflight) are final and
implemented; this section will be updated with the closing real-hardware
validation once those land.

## Validation

`make check` green with the new tests (`test_open_leaves_max_temp_directory_size_unset_by_default`,
`test_open_honors_explicit_max_temp_directory_size` in `test_graph.py`;
`test_cohort_score_handler_max_temp_directory_size_defaults_to_none`,
`test_cohort_score_handler_forwards_max_temp_directory_size` in
`test_platform_jobs.py`). `deploy-platform-runtime.yml` syntax-checked
against the example inventory. Real, live-verified against zimaworker1
(read-only where noted):

- The raised health floor correctly fails right now, before any
  remediation: `ansible-playbook health.yml --limit zimaworker1` reports
  "zimaworker1 has 0.8 GB free on /, below the 6 GB floor" — confirming
  the floor would have caught the original incident had it been set
  correctly beforehand.
- The new preflight correctly refuses a real dispatch to zimaworker1 at
  its current free space, and correctly passes against a healthy Pi
  worker (no false positive).
- The full `discogs` replica's `.verified.json`/`manifest.json` timestamps
  (2026-07-03/04) confirm it was fetched through the official checksummed
  path, not ad hoc — real evidence for the dataset-decision reasoning
  above, not an assumption.

**Pending real validation** (to be added here once complete): `/var/log`
root-caused and reduced; full `discogs` replica removed; a real
`research.graph-metrics` and a real full `cohort.score` dispatch both
succeeding end to end against zimaworker1 post-remediation.

Non-privileged diagnosis narrowed the `/var/log` candidate set without yet
confirming it (log content itself needs root, gated on operator action):
this host runs a full desktop CasaOS image (`gdm`/`gnome-shell` session,
`cups`/`cups-browsed`, `ModemManager`, `samba` `nmbd`/`smbd`,
`switcheroo-control`, `colord`, `packagekit`) alongside its compute-worker
role — `systemctl --failed` reports clean (no crash-looping unit), so the
volume more likely comes from routine chatter across several
desktop/peripheral-support daemons a headless worker doesn't need, not a
single broken service. Disabling the unneeded ones is a real, concrete
candidate action once log content confirms it, and separately reduces
future log volume regardless of the immediate cleanup.

**Dataset removal: done, real, operator-authorized.** The operator gave
explicit go-ahead; the full `discogs` replica was deleted from zimaworker1
(`ansible ... -m file ... state=absent`, the exact `local/cache/discogs`
path only). Verified immediately after: `discogs-onehop` untouched at
2.2G, root filesystem free space rose from 0.8G to 7.3G, and
`playbooks/health.yml`'s raised `min_free_gb: 6` floor now passes cleanly
against this host (previously correctly failing). This alone resolved the
disk-full state; `/var/log`'s exact root cause (Slice A) remains a
separate, smaller open item — see below.

**Still open at time of writing**: `/var/log`'s exact root cause (Slice A,
blocked on interactive root log access — the available non-interactive
mechanisms in this environment could not supply a sudo password) and a
real post-remediation `cohort.score`/`research.graph-metrics` dispatch
(Slice E, now unblocked by the dataset removal and safe to attempt). C, D,
and B are real, tested, and live-verified. This ADR's mechanism/policy
decisions stand as Accepted; this Consequences section is being updated in
place as each remaining item closes, rather than superseded by a new ADR.

## Revisit trigger

Revisit if, after full remediation, a real `cohort.score` run still fails
on disk/spill grounds — that would be real evidence this hardware cannot
host this workload's worst case even when properly governed, and the
honest next step is the ADR 0013-pattern hardware upgrade, not further
software tightening. Revisit `min_free_gb: 6` / the preflight defaults
once real post-remediation headroom is measured, if they turn out to be
miscalibrated in either direction. Revisit `platform_release_keep_count: 3`
if rollback ever needs to reach further back than that.
