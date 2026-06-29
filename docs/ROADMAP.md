# Roadmap

The roadmap favors one complete vertical path over broad parallel scaffolding.

## 0. Foundation

- [x] Select the Networked Players name
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

## 2. Distributed proof

- [ ] Initialize a single-manager Swarm
- [ ] Build or select one harmless AMD64/ARM64 image
- [ ] Run a bounded service on each worker
- [ ] Remove and rejoin one worker
- [ ] Back up and test recovery of manager state

## 3. Collection-slice data path

- [ ] Define the smallest private seed import contract
- [ ] Normalize a small release and credit slice
- [ ] Expand one catalog hop
- [ ] Produce versioned Parquet and validation queries
- [ ] Manually verify at least one evidence path

## 4. First playable artifact

- [ ] Define a static challenge schema
- [ ] Generate one challenge from the verified path
- [ ] Build a small accessible browser experience
- [ ] Show release-level evidence for every step
- [ ] Confirm full use with all home services disabled

## 5. Measured expansion

- [ ] Add repeatable RQ worker jobs
- [ ] Measure snapshot size, transfer, memory, and execution limits
- [ ] Compare readable fixtures with optimized graph representations
- [ ] Expand challenge generation and public findings

## 6. Optional live search

- [ ] Define bounded request and response contracts
- [ ] Add caching, rate limits, validation, and observability
- [ ] Review exposure and failure behavior
- [ ] Keep static use fully available during outages
