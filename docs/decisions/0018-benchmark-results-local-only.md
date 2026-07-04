# ADR 0018: Benchmark results are local-only; the method stays public

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

[ADR 0001](0001-public-by-default.md) classified "benchmarks" as public
alongside source code, schemas, and tests, and `docs/HARDWARE.md`'s
"Measured capability" table published real, instance-specific throughput
numbers (releases/sec, elapsed time, peak RSS) for the coordination host and
the joined Pi 3B workers, dated 2026-07-02.

While extending benchmarking to add a cluster-vs-single-node comparison
(see [ADR 0019](0019-cluster-benchmark-rq-job-broker.md)), the operator asked
that hardware/benchmark details generally move to local-only going forward,
including retroactively removing the numbers already committed to
`docs/HARDWARE.md`. This is a deliberate narrowing of ADR 0001's "benchmarks"
classification, not an oversight — it reflects a preference to keep this
specific home lab's measured performance characteristics (which double as
fingerprintable details about the real, running environment) out of the
public repository, while keeping everything that makes the benchmark
reproducible (the probe code, the Ansible playbooks, the RQ-based
distributed-comparison driver) public.

## Decision

Split "benchmark" into two categories going forward:

1. **Benchmark method (public, unchanged):** `infra/ansible/files/benchmark_parse.py`,
   `infra/ansible/playbooks/benchmark.yml`, and the new cluster-vs-single-node
   RQ-based driver (ADR 0019) all stay public source code. Anyone can clone
   this repo and reproduce a measurement on their own hardware.
2. **Benchmark result (private and local, new):** the actual numbers a run
   produces — hostname-adjacent throughput, elapsed time, peak memory — are
   written under `local/benchmarks/` (gitignored via the existing blanket
   `local` rule) and never transcribed into a committed doc.

Concretely:

- Amend `docs/PUBLIC_PRIVATE_BOUNDARY.md`'s "Public" list to say benchmark
  *methodology* is public, not benchmark *results*, and add a line to its
  "Practical pattern" section pointing at `local/benchmarks/`.
- Rewrite `docs/HARDWARE.md`'s "Measured capability" section: remove the real
  numbers, keep only a pointer to `make cluster-benchmark` /
  `make cluster-benchmark-distributed` and a note that output lives in
  `local/benchmarks/`. The separate hardware-*class* table earlier in that
  file (node roles, models, constraints) is unaffected — hardware models
  remain public per ADR 0001.

## Consequences

The project loses its public "receipts" of measured throughput — a reader
can no longer see real numbers for this specific lab's Pi 3B or ZimaBoard
without running the benchmark themselves. This is an accepted tradeoff for
keeping instance-specific performance characteristics of the real, running
environment out of the public repository. The benchmark code, playbooks, and
methodology remain fully public and reproducible, so the educational/
portfolio value ADR 0001 cared about is preserved at the method level, just
not the specific-numbers level.

This does not change ADR 0001's broader public-by-default posture for
anything else (source, schemas, tests, architecture) — it narrows one
specific bullet.

## Validation

`git diff docs/HARDWARE.md` shows the numeric throughput table replaced by
prose with no measured figures. `git check-ignore -v local/benchmarks/` (once
that directory exists locally) confirms it's excluded from version control
via the existing blanket `local` rule.

## Revisit trigger

Revisit if the project later wants to publish an anonymized or aggregate
figure (e.g. "roughly 3x throughput difference between node classes")
without disclosing exact numbers — that would be a narrower, deliberate
carve-out, not a reversal of this ADR.
