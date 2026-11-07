# Roadmap

This is the canonical "where we are / what's next" page. Other planning docs are either
direction ([GRAPH_EXPANSION_DIRECTION.md](GRAPH_EXPANSION_DIRECTION.md)), runbook
([EXPANSION_PIPELINE.md](EXPANSION_PIPELINE.md)), historical breakdown
([BUILD_PLAN.md](BUILD_PLAN.md)), or closed reports under [archive/](archive/).

## Where we are (2026-11)

- **Live and static** at `networked-players.com`: a real 217-album catalog (expansion Round 1,
  179 → 217, PR #246), four game modes, Explore, Connect Two Records, and contributor pages,
  all served as static artifacts with no required live endpoint.
- **Public graph is performer-only** ([ADR 0068](decisions/0068-performer-only-public-graph.md))
  and published as `graph.v4` ([ADR 0071](decisions/0071-pathfinding-graph-v4-role-dictionary.md)).
- **Daily schedule** (Connection of the Day) runs through 2027-02-26; extend it with
  `extend-connection-daily-manifest-v2` before the weekly `daily-manifest-status` check's
  14-day warning (see [OPERATOR_SETUP.md](OPERATOR_SETUP.md)).
- **Known open budget:** Explore recenter p95 misses its 100 ms budget at both 179 and 217
  albums (pre-existing, accepted; numbers stay local per ADR 0018).

## What's next

In order; each step lands before the next starts.

1. **Stage 0 — runbook and inputs** (no owner input needed): rewrite
   [EXPANSION_PIPELINE.md](EXPANSION_PIPELINE.md) steps 1–8 to match how Round 1 actually ran
   (supply stage first), document the daily-manifest freeze → migrate → extend sequence,
   record real `--masters-root` usage and `--previous-routes-universe`, re-measure the
   relationship pool without `--limit` and coverage gaps against 217, and add rounds 2–5 to
   `data/albums/expansion-policy-v1.json`.
2. **Stage 1 — one owner review** of an approved candidate pool, recorded as
   `data/albums/approved-pool-v1.json`.
3. **Round 2** — 217 → ~277 albums.
4. **Phase 3 product work** — `catalog/candidates.v1.json` (candidate albums in search), a
   build manifest, the `featured` badge and roster, Explore as the hero entry point, and
   retiring `/demo/`.
5. **Round 3** — ~277 → ~357, plus a final community-detection decision
   ([ADR 0070](decisions/0070-community-detection-and-explore-scaling-measurement.md)).
6. **Graph artifact compaction** — must land before the catalog passes ~500 albums;
   `graph.v4` is already close to its gzip budget.
7. **Rounds 4–5** — to ~500+.

Deliberately deferred: a Discogs snapshot refresh (snapshot 20260601 is kept through
Round 2), [ADR 0061](decisions/0061-scope-tier-corpus-design-deferred.md) and
[ADR 0062](decisions/0062-pi-fleet-verify-challenge-migration-deferred.md).

## Phase gates (original checklist)

The original study-lab phase gates, kept as a record. Unchecked items are still open but are
not the current priority unless they appear above.

### 0. Foundation

- [x] Select the Networked Players name
- [x] Register `networked-players.com` as the eventual production game host
- [x] Create the public monorepo
- [x] Establish public/private and rights boundaries
- [x] Record the initial product and architecture direction
- [x] Select a license before inviting reusable code contributions (MIT, 2026-08-04 — code only,
      not Discogs-derived data/artifacts; see `docs/DATA_AND_RIGHTS.md`)

### 1. Baseline hardware

- [x] Confirm supported 64-bit operating systems
- [x] Establish local naming and addressing outside Git
- [x] Verify SSH access, time synchronization, storage, power, and temperatures
- [x] Run an idempotent Ansible facts and health playbook
- [x] Write and test coordination-host recovery notes locally

### 2. Swarm skeleton

- [x] Initialize a single-manager Swarm
- [x] Build or select one harmless AMD64/ARM64 image
- [x] Run a bounded service on each worker
- [x] Remove and rejoin one worker
- [x] Back up and test recovery of manager state

### 3. Discogs acquisition and collection slice

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

### 4. Durable contracts

- [ ] Version normalized artist, master, label, identifier, format, and company schemas as needed
      (masters done; artist/label remain embedded in credits, not standalone schemas)
- [x] Preserve source role text while defining a role taxonomy (role text preserved
      verbatim everywhere; taxonomy defined as a third orthogonal classification layer,
      `role_taxonomy.py`, ADR 0047, Phase 2 Slice B; real coverage extended 2026-08-04
      from a Jamiroquai-corpus measurement, `docs/archive/PHASE3_REPORT.md`'s follow-up section)
- [x] Define snapshot retention, free-space guardrails, and recovery automation
- [x] Define graph-snapshot and static-challenge contracts
- [ ] Add mutable registry or search state only when the vertical slice requires it
      (ongoing constraint, not yet triggered)

### 5. First playable static release

- [x] Generate one challenge from the verified path (real since 2026-07-20 —
      `challenge.v2.json`, 140 albums, snapshot 20260601; see `docs/BUILD_PLAN.md`)
- [x] Build a small accessible browser experience
- [x] Show release-level evidence for every step
- [ ] Confirm full use with all home services disabled (pending live gate H)
- [x] Deploy the static game shell to `networked-players.com` through Cloudflare's Git integration

### 6. Medium graph and measured expansion

- [x] Add repeatable RQ worker jobs over immutable partitions
- [x] Consolidate those jobs behind the ADR 0034 capability and provenance runtime
      (2026-08-04 -- all three Pi workers plus the x86 worker are real, live
      participants; the 8 old `scripts/enqueue_*_check.py` fleet-validation scripts
      were migrated onto `artifact.validate` + `scripts/submit_artifact_check.py`
      and retired, real-verified against the live fleet including redundant
      fan-out across all 3 Pis; see ADR 0056)
- [ ] Measure snapshot size, transfer, memory, and execution limits on each hardware class
      (Phase 3 Slice E measured one real case -- a bounded validation-class job's
      locality/transfer/compute cost on x86 vs. a real Pi 3B, see
      `docs/RESEARCH_COMPUTE_LOCALITY_METHOD.md` -- not yet a comprehensive
      per-hardware-class measurement)
- [ ] Expand challenge generation and public findings
- [x] Verify repeated publication and rollback (real drilled revert-and-restore against a
      live Phase-4 artifact, 2026-08-08 -- see `docs/OPERATOR_SETUP.md`'s Rollback section,
      PRs #96/#97, ADR 0058 Slice 11)

### 7. Graph benchmark gate

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

### 8. Full scale

- [ ] Parse all required dump types within acceptable resource limits
- [ ] Produce compact versioned publication artifacts
- [ ] Demonstrate reproducible rebuild and rollback
- [ ] Keep optional workstation compute outside the uptime contract

### 9. Optional live search

- [ ] Define bounded request and response contracts
- [ ] Add caching, rate limits, validation, and observability
- [ ] Review exposure and failure behavior
- [ ] Keep static use fully available during outages
