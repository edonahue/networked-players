# Research compute locality benchmark method (Phase 3 Slice E)

Answers Slice E's "one real locality/transfer benchmark" requirement:
does it matter, for a real bounded research job, whether data is already
local to the worker computing it? Real measured numbers on real hardware
are never published here (ADR 0018) — this document is the reproducible
methodology and the qualitative conclusion; real timings live in
`local/benchmarks/` (gitignored).

## What's measured, and how

**Workload**: `research.corpus-check` (`packages/platform/.../workloads.py`
`_research_corpus_check_handler`) — a bounded checksum/size audit of a
topic corpus's real on-disk files against its own `manifest.json`. Chosen
because it is the one workload in this slice both worker classes (Pi and
x86) are eligible for (`tags=("validation",)`), and because it is small
and self-contained enough to run identically as a standalone script with
zero package installation.

**Two cases, same corpus** (the real Jamiroquai topic corpus, ~3.8 MB
across 4 files):

1. **Already resident, in-process, x86_64** — the coordinator already has
   the corpus on local disk (it built it); the check runs directly
   against it, no network hop, no dispatch step.
2. **Not resident, dispatched to a Pi 3B** — the same corpus is staged to
   a real Raspberry Pi 3B worker over the local network (via Ansible;
   the Pi fleet is not yet onboarded onto the RQ-based capability
   platform for this workload class — see this slice's PR notes — so
   this is a one-off manual exercise of the same handler logic, not a
   real queued dispatch), executed there, and the report fetched back.

Both cases run the identical checker logic (the same
`_research_corpus_check_handler` body, extracted to a standalone
zero-dependency script so it can run on the Pi's system Python3 with no
install step) and record two numbers: wall-clock time for the whole
operation, and compute-only time (parsed from the script's own internal
timer around just the checksum verification, excluding I/O staging).

## Decision framework

Not "is the Pi slower" in the abstract (it obviously has less compute) —
whether *locality* specifically (data already present vs. requiring a
network hop plus dispatch orchestration) is a meaningful cost at the real
scale this platform's bounded jobs run at, and whether that cost is
dominated by transfer, compute, or orchestration overhead. That answer
changes what's worth optimizing later (e.g. a persistent dataset cache
vs. a faster dispatch path vs. accepting the Pi's slower CPU as a fixed
cost for validation-class work it was never meant to do heavy computation
for).

## Results (methodology only — see local/benchmarks/ for real figures)

- The compute-only cost of the identical bounded checksum workload is
  measurably higher on the Pi 3B than on the x86_64 coordinator — real,
  expected, consistent with the Pi 3B's much weaker CPU, though the
  absolute cost is small in wall-clock terms even on the Pi at this
  corpus size.
- The *dominant* cost in the Pi case, by a wide margin, is not data
  transfer (the corpus is a few megabytes) or compute — it is
  orchestration overhead: each Ansible module invocation pays its own SSH
  connection setup, and this one-off exercise used several sequential
  invocations (stage directories, copy the corpus, copy the script, run
  it, fetch the report, clean up).
- The already-resident, in-process x86 case pays none of that cost —
  a real, clear locality win for any workload where the option exists
  (data replicated ahead of time, per ADR 0023's existing x86-worker
  dataset-replication precedent).

## Conclusion this evidence supports

**Locality matters, but mostly via orchestration overhead, not raw
transfer or compute cost, at this platform's real (small, bounded) job
sizes.** This reinforces two decisions already made elsewhere in this
phase: `research.graph-metrics` stays x86-only (heavier compute,
benefits from x86's advantage directly); `research.corpus-check` stays
validation-class and Pi-eligible (its compute cost is small enough that
the Pi's slower CPU is not a real constraint — the constraint, if any,
would be dispatch frequency/overhead at scale, not this job's own cost).
Neither conclusion required inventing a new scheduler or dataset-locality
mechanism beyond what ADR 0034/0023 already provide.

## What wasn't completed (explicit follow-ups)

- The Pi fleet is not yet onboarded onto the RQ-based capability platform
  for real queued dispatch (missing `platform_worker_id`/memory-limit
  configuration, unverified systemd-linger state on each Pi) — this
  benchmark used a one-off manual Ansible exercise of the same handler
  logic instead of a real `select_worker()`-routed job, which is an
  honest limitation of this specific measurement, not a claim that the
  Pi fleet fully participates in the capability platform yet. Full Pi
  onboarding is real, unsupervised, first-time production configuration
  work on hardware this session could not visually verify — deliberately
  left as an explicit, documented follow-up rather than attempted
  unsupervised overnight.
- Orchestration overhead itself (e.g. a persistent SSH connection, or
  batching multiple staging steps into one Ansible play) was not
  separately optimized or re-measured — this benchmark reports the cost
  as observed with the tooling this project already has, not a tuned
  best case.
