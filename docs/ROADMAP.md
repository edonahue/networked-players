# Roadmap

The roadmap follows the study lab's phase gates while favoring one complete vertical path over broad parallel scaffolding.

See [docs/BUILD_PLAN.md](BUILD_PLAN.md) for the granular, code-level task breakdown from today's state through MVP to production.

## 0. Foundation

- [x] Select the Networked Players name
- [x] Register `networked-players.com` as the eventual production game host
- [x] Create the public monorepo
- [x] Establish public/private and rights boundaries
- [x] Record the initial product and architecture direction
- [x] Select a license before inviting reusable code contributions (MIT, 2026-08-04 — code only,
      not Discogs-derived data/artifacts; see `docs/DATA_AND_RIGHTS.md`)

## 1. Baseline hardware

- [x] Confirm supported 64-bit operating systems
- [x] Establish local naming and addressing outside Git
- [x] Verify SSH access, time synchronization, storage, power, and temperatures
- [x] Run an idempotent Ansible facts and health playbook
- [x] Write and test coordination-host recovery notes locally

## 2. Swarm skeleton

- [x] Initialize a single-manager Swarm
- [x] Build or select one harmless AMD64/ARM64 image
- [x] Run a bounded service on each worker
- [x] Remove and rejoin one worker
- [x] Back up and test recovery of manager state

## 3. Discogs acquisition and collection slice

- [x] Record the hybrid private-seed, dump, and optional-API strategy
- [x] Add a versioned monthly manifest and checksummed download scaffold
- [x] Add a streaming synthetic release parser and normalized evidence contract
- [x] Add bounded Parquet output and DuckDB validation tests
- [x] Measure a real compressed release dump on the planned storage host
- [x] Define the smallest private seed import contract
- [x] Create matching synthetic seed fixtures
- [x] Run a 10,000-release local slice and record time, memory, and bytes
- [x] Extract a private seed and expand one catalog hop (real run done 2026-07-05,
      gate B — 1,410,106 releases, validated clean; see `docs/BUILD_PLAN.md`)
- [x] Manually verify at least one evidence path (gate F closed 2026-07-20;
      see `docs/BUILD_PLAN.md`)

## 4. Durable contracts

- [ ] Version normalized artist, master, label, identifier, format, and company schemas as needed
      (masters done; artist/label remain embedded in credits, not standalone schemas)
- [x] Preserve source role text while defining a role taxonomy (role text preserved
      verbatim everywhere; taxonomy defined as a third orthogonal classification layer,
      `role_taxonomy.py`, ADR 0047, Phase 2 Slice B)
- [x] Define snapshot retention, free-space guardrails, and recovery automation
- [x] Define graph-snapshot and static-challenge contracts
- [ ] Add mutable registry or search state only when the vertical slice requires it
      (ongoing constraint, not yet triggered)

## 5. First playable static release

- [x] Generate one challenge from the verified path (real since 2026-07-20 —
      `challenge.v2.json`, 140 albums, snapshot 20260601; see `docs/BUILD_PLAN.md`)
- [x] Build a small accessible browser experience
- [x] Show release-level evidence for every step
- [ ] Confirm full use with all home services disabled (pending live gate H)
- [x] Deploy the static game shell to `networked-players.com` through Cloudflare's Git integration

## 6. Medium graph and measured expansion

- [x] Add repeatable RQ worker jobs over immutable partitions
- [ ] Consolidate those jobs behind the ADR 0034 capability and provenance runtime
      (the runtime itself is implemented, `packages/platform`; the older
      `scripts/enqueue_*_check.py` fleet-validation family still uses the
      pre-0034 hostname/inventory-group pattern, not yet migrated onto it)
- [ ] Measure snapshot size, transfer, memory, and execution limits on each hardware class
      (Phase 3 Slice E measured one real case -- a bounded validation-class job's
      locality/transfer/compute cost on x86 vs. a real Pi 3B, see
      `docs/RESEARCH_COMPUTE_LOCALITY_METHOD.md` -- not yet a comprehensive
      per-hardware-class measurement)
- [ ] Expand challenge generation and public findings
- [ ] Verify repeated publication and rollback

## 7. Graph benchmark gate

- [x] Keep readable fixtures as the correctness oracle
- [x] Compare compact arrays with at least one optimized graph library
      (NetworkX/igraph/rustworkx vs. DuckDB/CSR at topic-corpus scale, Phase 3
      Slice C; see `docs/RESEARCH_GRAPH_BENCHMARK_METHOD.md` and ADR 0055)
- [x] Record hardware, dataset version, method, and results (method public,
      real numbers in `local/benchmarks/` per ADR 0018)
- [x] Select the production representation only after measurement (igraph
      selected for offline research analytics, ADR 0055 -- `graph.py`'s
      DuckDB-backed production traversal path is unchanged; this gate was
      about research/offline analytics, not the public game's own path)

## 8. Full scale

- [ ] Parse all required dump types within acceptable resource limits
- [ ] Produce compact versioned publication artifacts
- [ ] Demonstrate reproducible rebuild and rollback
- [ ] Keep optional workstation compute outside the uptime contract

## 9. Optional live search

- [ ] Define bounded request and response contracts
- [ ] Add caching, rate limits, validation, and observability
- [ ] Review exposure and failure behavior
- [ ] Keep static use fully available during outages
