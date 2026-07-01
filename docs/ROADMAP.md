# Roadmap

The roadmap follows the study lab's phase gates while favoring one complete vertical path over broad parallel scaffolding.

See [docs/BUILD_PLAN.md](BUILD_PLAN.md) for the granular, code-level task breakdown from today's state through MVP to production.

## 0. Foundation

- [x] Select the Networked Players name
- [x] Register `networked-players.com` as the eventual production game host
- [x] Create the public monorepo
- [x] Establish public/private and rights boundaries
- [x] Record the initial product and architecture direction
- [ ] Select a license before inviting reusable code contributions

## 1. Baseline hardware

- [ ] Confirm supported 64-bit operating systems
- [ ] Establish local naming and addressing outside Git
- [ ] Verify SSH access, time synchronization, storage, power, and temperatures
- [ ] Run an idempotent Ansible facts and health playbook
- [ ] Write and test coordination-host recovery notes locally

## 2. Swarm skeleton

- [ ] Initialize a single-manager Swarm
- [ ] Build or select one harmless AMD64/ARM64 image
- [ ] Run a bounded service on each worker
- [ ] Remove and rejoin one worker
- [ ] Back up and test recovery of manager state

## 3. Discogs acquisition and collection slice

- [x] Record the hybrid private-seed, dump, and optional-API strategy
- [x] Add a versioned monthly manifest and checksummed download scaffold
- [x] Add a streaming synthetic release parser and normalized evidence contract
- [x] Add bounded Parquet output and DuckDB validation tests
- [ ] Measure a real compressed release dump on the planned storage host
- [ ] Define the smallest private seed import contract
- [ ] Create matching synthetic seed fixtures
- [ ] Run a 10,000-release local slice and record time, memory, and bytes
- [ ] Extract a private seed and expand one catalog hop
- [ ] Manually verify at least one evidence path

## 4. Durable contracts

- [ ] Version normalized artist, master, label, identifier, format, and company schemas as needed
- [ ] Preserve source role text while defining a role taxonomy
- [ ] Define snapshot retention, free-space guardrails, and recovery automation
- [ ] Define graph-snapshot and static-challenge contracts
- [ ] Add mutable registry or search state only when the vertical slice requires it

## 5. First playable static release

- [ ] Generate one challenge from the verified path
- [ ] Build a small accessible browser experience
- [ ] Show release-level evidence for every step
- [ ] Confirm full use with all home services disabled
- [ ] Deploy the game to `networked-players.com`

## 6. Medium graph and measured expansion

- [ ] Add repeatable RQ worker jobs over immutable partitions
- [ ] Measure snapshot size, transfer, memory, and execution limits on each hardware class
- [ ] Expand challenge generation and public findings
- [ ] Verify repeated publication and rollback

## 7. Graph benchmark gate

- [ ] Keep readable fixtures as the correctness oracle
- [ ] Compare compact arrays with at least one optimized graph library
- [ ] Record hardware, dataset version, method, and results
- [ ] Select the production representation only after measurement

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
