# ADR 0025: Worker-local, disposable, verified dataset caches

- **Status:** Accepted
- **Date:** 2026-07-04

## Context

[ADR 0024](0024-http-readonly-catalog-data-access.md) closed the "workers have no path to the data" gap with a read-only HTTP layer, but every job still re-reads the dataset over the LAN on every run. The full parsed snapshot is an observed 6.6 GB of Parquet (credits 3.9 GB, tracks 2.3 GB, releases 0.44 GB) — small enough that the x86 worker (ADR 0022/0023, 1 GbE, 7.6 GB RAM) can hold a full local replica cheaply, and doing so avoids repeated wire transfers for repeated real-data work (benchmarks, notebook runs, the challenge-artifact builder). The operator asked for this explicitly, with one hard constraint carried over from the node-model correction: **the master/coordination host stays the single authoritative source for `local/processed/`; nothing else may become authoritative.**

Pi 3B workers (1 GB RAM, 100 Mbps) keep ADR 0024's existing bounded-only policy — they may cache the one-hop working set (small, seed-derived) but never the full catalog, even though disk space alone wouldn't stop them. The rule has to be enforced structurally, not by operator discipline, matching this project's existing pattern of making unsafe operations mechanically impossible rather than merely documented against (e.g. `harden-workers.yml`/`equip-workers.yml` being retargeted to `pi_workers` in ADR 0022 specifically so a fleet-wide run can't accidentally hit a non-Pi host).

## Decision

**A self-contained fetch/verify tool** (`packages/catalog/src/networked_players_catalog/discogs/dataset_fetch.py`) — stdlib-only, runnable under a bare worker `python3` with no venv — reads a dataset's `manifest.json` from the ADR 0024 HTTP layer, downloads every file, verifies each one's sha256, and writes a `.verified.json` marker only once every file matches. A local dataset directory is a **"validated cache"** only when both `manifest.json` and `.verified.json` are present; nothing else in the project should treat an unmarked local directory as trustworthy. The fetch is staged and atomic (a persistent `.<name>.partial` staging directory, not a random one — so a retry resumes from whatever already-verified files survived a prior failed run, rather than redownloading everything) and idempotent (a second call against an already-valid destination short-circuits via `verify_dataset` without contacting the server at all).

**Two separate ansible playbooks enforce the per-class policy structurally**, not via a shared playbook with a policy flag an operator could get wrong:

- `replicate-dataset-x86.yml` (`hosts: x86_workers`) accepts `-e dataset=<discogs|discogs-onehop|discogs-masters>` — any of the three catalog datasets, full-size, matching ADR 0024's existing hybrid access policy for this hardware class.
- `replicate-dataset-pi.yml` (`hosts: pi_workers`) has **no `dataset` variable at all** — the dataset name is hardcoded to `discogs-onehop` in the playbook itself, so there is no `-e dataset=discogs` a Pi invocation could ever honor. It also always passes a pre-download byte guard (`pi_cache_max_bytes`, default 2 GiB) to `dataset_fetch.py`, which checks the served manifest's total size **before downloading anything** and refuses if it's exceeded.

Both playbooks copy `dataset_fetch.py` directly from the `packages/catalog` checkout on the control node — one source of truth, not a maintained duplicate under `infra/ansible/files/`.

**Cache location:** a new group_vars variable, `catalog_cache_root`, with no default (a wrong guess could silently cache into the wrong filesystem) — a real absolute path lives in the git-ignored local inventory, a placeholder in the committed example. Layout under it mirrors the master's own convention: `<catalog_cache_root>/<dataset>/snapshot=<X>/`.

**Rsync fallback, actually implemented, not just documented:** `scripts/replicate-rsync.sh` (run from the master, which already has SSH access to its workers) rsyncs a dataset to a worker for the bulk-transfer case where the HTTP pull is impractically slow, then prints the exact `--verify-only` command to run afterward — rsync itself does not produce a `.verified.json` marker, so a synced copy is not yet a "validated cache" until that verify step runs. This is x86-only; Pi's always go through the guarded playbook.

**Resolution order** (`dataset_locator.resolve_dataset(dataset, snapshot, env=...)`): (1) a validated local cache via `CATALOG_DATA_DIR` — skipped if `manifest.json` exists but `.verified.json` doesn't, since an unverified cache is never preferred over a fresh HTTP read; (2) the ADR 0024 HTTP layer via `CATALOG_DATA_URL`; (3) otherwise raise, naming both env vars and what was checked, so a job fails loudly instead of silently reading nothing. `run-dask-worker-burst.yml` and `run-rq-burst-worker.yml` both gained an optional `-e catalog_data_dir=...` → `--setenv=CATALOG_DATA_DIR=...`, parallel to ADR 0024's existing `catalog_data_url` wiring (systemd-run does not inherit the invoking environment — the same gotcha ADR 0021/0024 already documented).

**Staleness model:** datasets are immutable by convention (staging + atomic rename, ADR 0006's own pattern extended to the one-hop and masters writers) — a worker cache never goes stale *across* snapshots, since a new snapshot is simply a new directory. Re-ingesting the *same* snapshot date does invalidate any cache built from it; nothing here detects that automatically, so a worker cache must be explicitly re-replicated after any such re-ingest. Caches are disposable and never backed up — rebuilding one is just re-running the fetch.

## Consequences

Real-data work on the x86 worker (benchmarks, notebook 02, the challenge-artifact builder) no longer re-reads the dataset over the LAN on every invocation, at the cost of the worker's own disk holding a second (disposable) copy of up to the full 6.6 GB dataset. The master remains the only host anything else should treat as authoritative — a stale or corrupted worker cache is a local, low-stakes problem, fixed by deleting the directory and re-running the fetch, never a data-integrity incident. The Pi bounded-only rule from ADR 0024 is now enforced by the shape of a playbook, not just stated in a document. No new stateful service was introduced — the fetch tool talks to the same nginx layer ADR 0024 already runs.

## Validation

`packages/catalog/tests/test_dataset_fetch.py` (11 tests) and `test_dataset_locator.py`'s `resolve_dataset` additions (4 tests) run against a real loopback HTTP server over synthetic data: happy-path fetch, tampered-served-file rejection (nothing left at the final path), idempotent re-run (verified without any network call), resumption from a pre-staged matching file, the max-total-bytes and free-disk-headroom guards, manifest path-traversal rejection, and the full local-cache → HTTP → error resolution order. Both new playbooks and the two edited ones pass `ansible-playbook --syntax-check` against the example inventory. `scripts/replicate-rsync.sh`'s guard clauses (unknown dataset, malformed snapshot, missing local dataset) were exercised directly. The live gate — replicating a real snapshot to the x86 worker and one Pi and verifying both — is an operator step (BUILD_PLAN / this session's live gates), not exercised in CI.

## Revisit trigger

Revisit toward concurrent/parallel fetching in `dataset_fetch.py` only if a real replication run's measured wall-clock time (over 11k+ small files for a full snapshot) proves the sequential fetch impractical — not speculatively. Revisit the Pi one-hop-only rule and its 2 GiB guard only with measured evidence from a real Pi workload, per ADR 0024's own identical trigger. Revisit cache eviction/retention policy if worker disk usage from accumulated old-snapshot caches ever becomes a real problem — nothing here automatically prunes a superseded snapshot's cache today.
