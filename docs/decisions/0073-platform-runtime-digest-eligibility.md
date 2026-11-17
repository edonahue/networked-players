# ADR 0073: Worker eligibility by runtime digest, not exact commit

- **Status:** Proposed
- **Date:** 2026-11-16
- **Depends on:** [ADR 0034](0034-capability-routed-home-compute-platform.md) (the exact-commit rule this refines), [ADR 0056](0056-unify-pi-fleet-checks-onto-capability-platform.md), [ADR 0018](0018-benchmark-results-local-only.md)
- **Campaign:** Atlas work package I1 (platform reliability)

## Context

ADR 0034 requires "every run is immutable and provenance-bearing" and implemented that as
exact-commit equality: `select_worker()` accepts a worker only when its advertised
`runtime_commit` equals the `git rev-parse HEAD` of the (clean) checkout that submits the
job, and the executor re-checks the same equality on the worker. The goal was right -- never
run a job on code the submitter did not intend, never mix code versions. The mechanism is
over-narrow, and three further reliability gaps sit around it. All four are documented in
`docs/OPERATOR_SETUP.md` and `docs/ATLAS_TRANCHE_1_REPORT.md`, not hypothetical.

1. **Every commit un-schedules the fleet.** A commit that changes only `docs/`, `apps/web/`
   or a data artifact changes `HEAD` but not one byte of code any worker executes. The whole
   fleet becomes ineligible until the runtime is rebuilt and redeployed, and the failure is a
   bare "no eligible worker".
2. **Stale contracts fail confidently and wrongly.** Workers validate with whatever
   `networked_players_contracts` is installed in the release venv, which exists only as of the
   last `make platform-deploy` (the `equip-workers.yml` contracts install targets a different,
   legacy venv and is easy to mistake for it), and the package version is the constant `0.1.0` (it has never been bumped: checked
   in `packages/contracts/pyproject.toml` and `__init__.py`). A newly keyed or schema-bumped
   artifact then fails fleet-wide with "unexpected top-level keys", and the validation report
   records nothing about which contracts produced it.
3. **Retry is nominal.** Workload specs declare `max_retries`, but every submit script builds
   requests with `max_retries=0` and `enqueue_and_wait` passes `retry=None`. A worker that
   disappears mid-job leaves an orphan and the client times out.
4. **No operator view or control.** Nothing lists jobs, shows a failure or its location, or
   cancels a job.

## Evidence

- The scheduler comparison is `worker.runtime_commit != runtime_commit` in
  `packages/platform/.../scheduler.py`; the executor refuses with "request/runtime commit
  mismatch".
- `docs/OPERATOR_SETUP.md` records a fleet run that first needed a rebuild and redeploy
  because the fleet's previously deployed runtime commit predated the merge.
- `data/contracts/artifact-lineage-v1.md` ("Fleet ordering") records the stale-contracts
  failure mode and that the report cannot attribute it.
- Package versions never change (`0.1.0` everywhere), so a version string cannot detect a
  code change; only content can.

## Alternatives considered

- **Keep exact commit; make redeploys cheaper.** Preserves ADR 0034 verbatim but leaves the
  fleet one docs commit from unschedulable, and each redeploy is operator work on a
  constrained fleet. Rejected: it optimises the cost of the symptom.
- **Package version / semver gate.** Versions are constants today; bumping them by hand
  recreates the stale-code risk through human error. Rejected.
- **Match on the git tree hash of `packages/`.** Cheap at submit time, but the worker has no
  git tree, only installed code, so the worker cannot compute it from what it runs and the two
  sides can only agree by trust. It also changes on tests and READMEs under `packages/`.
  Rejected: a digest must be computable from the executed artifact itself.
- **Wheel file hashes.** Exact for the installed files, but wheels are not reproducible
  byte-for-byte across builds (timestamps, metadata), and the submit side would need a built
  wheel. Rejected in favour of hashing the source content the wheel installs.

## Decision

1. **Eligibility is by runtime digest.** `runtime_digest` is a SHA-256 over the content of
   the first-party code a worker executes for a workload: every file (except `__pycache__`
   and `*.pyc`) of each `networked_players_*` package in that workload's import closure.
   Hashing every file, not an extension allowlist, means a packaged non-Python file cannot
   escape the digest. Files are hashed individually and combined in sorted relative-path
   order, so the digest is independent of file order, mtime and the filesystem. Docs,
   tests, the web app, data artifacts, READMEs and `*.egg-info` are outside every package
   directory; a commit that touches only those yields the same digest.
2. **The closure is determined, not guessed.** Starting from the module that registers the
   workload (the built-in `workloads` module, or a plugin entry point's module, both
   resolved without importing anything), an AST walk (including imports inside functions)
   collects every `networked_players_*` module reached; the digest covers every file of
   each reached *top-level package*, not only the reached modules, so a dynamic import
   inside an already-reached package cannot escape it. Plugin packages are located on
   demand, so no hard-coded package list can make one workload break another. The observed
   closures are listed in `packages/platform/README.md`, and tests assert them so that a
   new import that widens a closure is visible in review. `make platform-build` also runs
   `verify-wheels`: it unpacks the wheels it just built, recomputes every workload digest
   from the unpacked files, and refuses to build if they differ from the checkout's (or the
   file sets differ), so the code a worker installs is provably the code submitters hash.
3. **Per-workload digests, not one whole-runtime digest.** The Pi fleet installs only
   platform and contracts; x86 workers also install catalog, graph-core and research. A
   whole-runtime digest would make a Pi ineligible for `artifact.validate` when only
   `packages/catalog` changed, which is the over-invalidation this ADR removes. A worker
   therefore advertises `runtime_digests: {workload_id: digest}`; a request carries the one
   digest for its workload. The cost is a larger advertisement and one more concept in
   `platform-status`; the closures overlap heavily, so most digests move together. What would
   change this choice: if operators routinely cannot reason about which workloads a change
   affects, or the closures collapse to the same set, switch to one whole-runtime digest (a
   schema bump, not a rewrite).
4. **`uv.lock` is not in the digest; it is provenance only.** The campaign brief suggested
   including it. It is the whole-workspace lock (dev tools such as the linter and test
   runner included), so a dev-tool bump would un-schedule the fleet, and workers do not
   install from it: `deploy-platform-runtime.yml` resolves `redis` and `rq` by version
   bounds through `uv pip install`. Matching on it would create false skew while pinning
   nothing. The lock hash is still recorded in `release.json`. To be plain about it:
   third-party versions on workers were never pinned under the exact-commit rule either,
   and are not pinned now; the digest describes first-party code only. The revisit path is
   to export the resolved runtime dependency set of a workload's closure and install workers
   from that export, then fold the pins into the digest.
5. **Computed identically in three places** by one pure function: at build time
   (`make platform-build` records the digests in `release.json` after `verify-wheels`
   passes), on the worker (from the installed packages), and at submit time (from the
   checkout). What is hashed when, precisely: each package is hashed at most once per
   process however many workloads share it. The standing RQ worker hashes before its first
   job and caches the result for its lifetime (the forked work-horse inherits it, so no job
   re-hashes). The heartbeat unit is a separate one-shot process every 30 seconds, so it
   re-hashes the installed source of its workloads' packages on every tick; that is a
   small, bounded cost (the platform and contracts sources are about half a megabyte)
   accepted for simplicity, and the revisit trigger is a measured heartbeat problem. Submit
   hashes once per submit process. The executor re-verifies `request.runtime_digest`
   against the worker's own digest before importing the workload, then loads only the
   requested workload, so no other plugin's import-time code runs under that digest. One
   workload that cannot be hashed or imported is advertised as unavailable with a reason;
   the others stay advertised.
6. **Git commit remains recorded provenance.** Every request records the submitting
   checkout's commit; every result records the worker's built commit and its runtime digest.
   `runtime_commit` is information, not an eligibility key. ADR 0034's provenance requirement
   is preserved; only its equality gate is replaced. Submit still requires a clean checkout.
7. **Schema bump to 2 for advertisement, request and result.** Version-1 documents remain
   readable. A version-1 worker advertises no digests, so it is *ineligible with an explicit
   reason* (advertisement schema 1, no runtime digests, redeploy), never silently matched and
   never matched by commit. A worker missing a digest for one workload is ineligible for that
   workload only.
8. **Skew is explained, not silent.** Selection yields per-worker ineligibility reasons
   (stale heartbeat, digest mismatch showing both digests, missing workload version,
   architecture/tags/memory, dataset identity). `platform-status` shows each worker's digests,
   recorded commit, contracts version and whether it matches the local checkout; a failed
   selection reports the reasons.
9. **Validation reports attribute themselves.** `validation-report.json` (contract
   `platform-validation-report-v2`) records the `networked_players_contracts` package
   version, a content digest of the contracts package (needed because the version never
   changes), the runtime digest, the worker's built `runtime_commit` and the submitted
   commit, the worker id and the attempt. The report is the record that survives: the
   remote run is deleted after fetch and the RQ result expires. The artifact-check script
   also writes every attempt, orphans included, into its local per-worker record.
10. **Retries are honoured, idempotently.** Submitters use the workload's declared
    `max_retries` (overridable). Each attempt is a new request with a fresh run id, run
    directory and RQ job id, an `attempt` number and `retry_of`; the executor's "refuse to
    reuse an existing output" rule is untouched. **Lost-worker rule** (decided from RQ's own
    liveness, never from the advertisement): the RQ worker is live while its
    `rq:worker:<name>` record exists with a `last_heartbeat` at most 420 s old (RQ's default
    worker TTL, which the worker unit does not override); a worker is lost only after its
    RQ record has been absent or older than that for 60 further continuous seconds. The
    advertisement comes from a separate heartbeat unit, so its lapse alone never marks a
    worker lost and a worker with a live RQ record is never sent a stop command, while a
    dead RQ worker with a fresh advertisement is detected and also excluded from scheduling
    (a per-worker reason). The client deadline (job timeout + 60 s) only triggers a decision:
    a still-queued job is cancelled and re-dispatched, a started job with a worker heartbeat
    within 90 s is a genuine non-retryable timeout, and anything undecidable keeps being
    watched until the loss window (deadline + 420 + 60 + 30 s) ends, so a worker that dies just
    after enqueue on a 120 s workload is still recovered. On loss the client cancels a queued orphan (or stops a started one
    only after re-confirming lapsed RQ liveness), retries on another eligible worker if
    retries remain, and reports the orphan. Only infrastructure-class failures retry. A
    workload that raised is deterministic and does not. A work-horse killed by SIGKILL, or an
    abandoned job, cannot be told apart from an out-of-memory kill, so it is retried only on
    a worker with a strictly larger `max_job_memory_mb`, never on identical hardware.
11. **Operator control:** `jobs list|status|cancel|logs` on the existing platform CLI, reading
    only existing RQ/Redis state.

## What this does not protect against

- **Third-party dependencies.** Worker installs resolve `redis`, `rq`, `duckdb` and the like by
  version bounds via `uv pip install`, not from `uv.lock`; two workers can run different
  third-party versions under the same digest. This was equally true under exact-commit
  matching; the digest does not pretend otherwise.
- **Interpreter and OS differences** (Python minor version, libc, CPU architecture) are not in
  the digest; architecture remains a separate capability filter.
- **Tampering on a worker.** The worker computes its own digest honestly; a hostile host can
  advertise anything. This is a skew guard, not an attestation.
- **Code replaced on disk after a process started.** The digest is taken at process start; a
  changed install is not seen until restart.
- **Data and datasets**, which keep their own identity checks.
- **Deployment.** It remains an explicit operator action (build, deploy to all workers,
  verify). This ADR makes the need visible and attributable; it does not automate it.

## Consequences

Docs-only and web-only commits no longer un-schedule the fleet. A change to executed code or
the lock still does, and now says why. During rollout the fleet is mixed: version-1 workers
are refused with an explicit reason until redeployed, and the order is build, deploy to all
workers, verify the release venv's contracts with `platform-status`, then submit (see
`docs/OPERATOR_SETUP.md`). Hashing happens once per worker process start and once per submit.

Submitters are part of the rollout: a checkout from before this ADR rejects schema-2
advertisements outright and fails closed against an upgraded fleet (it cannot select any
worker); update the submitting checkout before or with the deploy. A malformed or unsupported
advertisement is skipped with a per-worker reason in the new code, rather than breaking
submit, `jobs` and status for everyone.

## Revisit triggers

- A third-party dependency skew causes a wrong result under a matching digest: pin worker
  installs to a lock export and fold the exported pins into the digest.
- Operators find per-workload digests confusing: collapse to one runtime digest.
- Closures grow so that most commits change every digest: the benefit is gone; revisit.
- A worker needs attestation against a hostile host: that needs signing, a different ADR.
