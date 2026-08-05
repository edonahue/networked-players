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
`--max-temp-directory-size`) sets it explicitly. This matters beyond just
fixing this incident: without a ceiling, a single heavy query could in
principle spill until a *shared* disk hits zero bytes free, degrading
CasaOS's own operation on the same filesystem, not just failing its own
job. The default was real-measured, not guessed: an initial `3GB` default
was tried against a real whole-catalog rescore on zimaworker1 post-
remediation and failed cleanly with DuckDB's own out-of-memory-class error
(real usage ~2.9GB at the point of failure); raised to `5GB` and the same
real rescore succeeded end to end (153.8s wall, 327.7MB peak RSS, well
within the 2GB `--memory-limit`, spill directory empty afterward). The
first attempt is exactly the mechanism working as designed — it stopped
the run at a predictable, chosen ceiling instead of letting it silently
consume the shared disk — just calibrated too low; the fix was retrying
with the existing `--max-temp-directory-size` flag, not a code change.

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

**No hardware change was required to unblock `cohort.score` — confirmed,
not just projected.** Dataset removal alone took real free space from
0.8G to 7.3G; the previously-failing workload then completed for real at
that headroom. A small dedicated data drive (reusing ADR 0013's proven
`/mnt/data` pattern — external drive, ext4, bind-mounted onto `local/`)
remains a reasonable optional future upgrade to permanently separate this
project's footprint from CasaOS's own, but is not needed to close this
incident and is not committed to here.

## Consequences

`CreditGraph.open()`'s new parameter is opt-in and additive — no behavior
change for any of the ~150 existing call sites that don't pass it.
`cohort.score` submissions now have a predictable worst-case disk
footprint instead of an implicit one tied to ambient free space.
Submission scripts gained one more required round-trip (the preflight) per
dispatch — a few hundred milliseconds of `df` over SSH, not a measurable
cost against jobs that run for minutes. The `min_free_gb` floor change
means `make cluster-health` correctly reported zimaworker1 unhealthy at
its pre-remediation free space and correctly reports it healthy now — the
guard doing its job in both directions, confirmed live.

The incident is closed: the exact workload that failed
(`cohort.score` against the real `discogs-community-best-albums` cohort)
now completes end to end on the same real hardware, with disk and RAM both
comfortably bounded. **Not yet closed**: `/var/log`'s exact spam source —
non-privileged diagnosis narrowed the candidate set (see Validation) but
confirming and fixing it needs root log access this session could not
obtain. This is real remaining technical debt, tracked by this ADR's own
Revisit trigger, not a blocker to anything else in this decision.

## Validation

`make check` green (871 passed) with the new tests
(`test_open_leaves_max_temp_directory_size_unset_by_default`,
`test_open_honors_explicit_max_temp_directory_size` in `test_graph.py`;
`test_cohort_score_handler_max_temp_directory_size_defaults_to_none`,
`test_cohort_score_handler_forwards_max_temp_directory_size` in
`test_platform_jobs.py`). `deploy-platform-runtime.yml` syntax-checked
against the example inventory. Merged via PR #85 with CI green; platform
runtime rebuilt and redeployed to all 4 real workers at the merged commit.
Real, live-verified against zimaworker1:

- **Health floor**: failed correctly pre-remediation ("zimaworker1 has 0.8
  GB free on /, below the 6 GB floor") and passed cleanly post-remediation.
- **Preflight**: correctly refused a real dispatch to zimaworker1 at low
  free space, and correctly passed against a healthy Pi worker (no false
  positive).
- **Dataset removal**: operator-authorized, executed
  (`ansible ... -m file ... state=absent` against exactly
  `local/cache/discogs`), `discogs-onehop` confirmed untouched at 2.2G,
  free space rose 0.8G → 7.3G. `.verified.json`/`manifest.json` timestamps
  (2026-07-03/04) independently confirmed the removed replica was fetched
  through the official checksummed path, matching the dataset-decision
  reasoning above.
- **Release-bundle pruning**: real deploy to all 4 workers exercised the
  new prune step live — zimaworker1 had a large backlog of old release
  directories (accumulated since the platform's introduction, never
  pruned before) cleared in the same run that deployed this fix.
- **`research.graph-metrics`**: real dispatch against the Jamiroquai
  corpus succeeded end to end (stage, dispatch, fetch, verify, retention
  cleanup all real).
- **`cohort.score`**: real dispatch against `discogs-community-best-albums`
  first failed at the initial `3GB` ceiling exactly as designed (a clean,
  named DuckDB error, not a disk-full crash), then succeeded at `5GB` --
  153.8s wall, 25 seeds, 118,222 reach rows, 327.7MB peak RSS, spill
  directory empty afterward. Free space actually *rose* to 8.7G after this
  run (retention cleaned up more accumulated old runs), directly
  confirming no disk leak under the fixed workload.
- **`/var/log` — stop condition triggered, formally.** This work's own
  plan named exactly this possibility in advance: "sudo/root log access to
  zimaworker1 isn't available to diagnose `/var/log` → Slice A blocked;
  fall back to a coarser fix ... without full root cause, and flag the gap
  honestly rather than guessing at the spam source." That is the real
  outcome here: no interactive terminal available to this work could
  supply the sudo password (a real, repeatedly-confirmed environment
  constraint, not a skipped step — `ansible -b -K` and the `usermod`
  group-membership workaround were both attempted and both failed
  non-interactively; `id erich`/`sudo -n -l` before and after confirm
  nothing changed). The "coarser fix" the plan names
  (`journalctl --vacuum-size=`, tightening `SystemMaxUse=`) *also* requires
  root, so even that fallback could not be applied this session — this is
  recorded here as a real, root-access-gated gap, not silently dropped.
  Non-privileged diagnosis (`ps`, `systemctl --failed`, process listing)
  narrowed the candidate set without confirming it: this host runs a full
  desktop CasaOS image (`gdm`/`gnome-shell`, `cups`/`cups-browsed`,
  `ModemManager`, `samba` `nmbd`/`smbd`, `switcheroo-control`, `colord`,
  `packagekit`) alongside its compute-worker role; `systemctl --failed`
  reports clean (no crash-looping unit), so the volume more likely comes
  from routine chatter across several desktop/peripheral-support daemons a
  headless worker doesn't need, not one broken service. Disabling the
  unneeded ones is the concrete next action once root access is available.

## Revisit trigger

**Open**: revisit once root log access to zimaworker1 is available —
confirm `/var/log`'s real spam source among the desktop/peripheral daemon
candidates named above, fix at the source (most likely disabling unneeded
services on what should be a headless compute worker), and record the real
before/after size here.

Revisit `--max-temp-directory-size 5GB` if a future cohort larger than the
25-seed `discogs-community-best-albums` set needs materially more spill
room than this measurement covered. Revisit `min_free_gb: 6` / the
preflight defaults if real headroom trends tighter again as CasaOS's own
footprint or dataset replicas grow. Revisit `platform_release_keep_count: 3`
if rollback ever needs to reach further back than that. Revisit the "no
hardware needed" conclusion only if disk pressure returns after this real
fix — at that point a dedicated data drive (ADR 0013's pattern) is the
next real option, not further software tightening.
