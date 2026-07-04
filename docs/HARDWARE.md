# Hardware context

The hardware is part of the learning story, but the public repository only needs enough detail to explain meaningful constraints.

## Current lab

| Hardware | Intended role | Important constraint |
| --- | --- | --- |
| Compact x86 coordination host (currently a ZimaBoard 832) | Always-on coordination, state, storage, and orchestration | Modest compute; state and recovery need care |
| Three active Raspberry Pi 3B nodes (a fourth, plus a Pi 3B+, are planned but not yet revived) | Bounded ARM64 workers | 1 GB RAM and 10/100 Ethernet per node |
| Existing five-port cluster switch | Fan-out to the Pi workers | Worker links remain limited by Pi hardware |
| Tenda SM105 five-port 2.5GbE switch | Connect the router, coordination host, and cluster uplink | Unmanaged; improves backbone and placement, not Pi link speed |
| Dedicated x86_64 Swarm worker (a ZimaBoard 832) | Fixed compute in the orchestrated Swarm, alongside the Pi workers; participates in the same RQ/Dask fleet work at a higher-capability tier | Joined as a worker only, never promoted; RQ/Dask resource limits scaled to its real headroom, not Pi-sized; see ADR 0022 (amends ADR 0015) and ADR 0023 |

## Public documentation rule

Hardware classes and selected models may be named when they explain a design constraint. Do not publish a complete personal-machine inventory, real hostnames, addresses, MAC addresses, serial numbers, physical placement, port maps, tunnel configuration, or backup destinations.

## Design implications

- Pi jobs must fit comfortably within 1 GB RAM with explicit concurrency limits.
- Snapshot distribution should be incremental, checksummed, and infrequent enough for 100 Mbps worker links.
- The 2.5GbE backbone chiefly benefits the coordination host, uplink organization, future endpoints, and large transfers that do not terminate on a Pi 3B.
- Heavy full-catalog work can run on an optional workstation and publish compact immutable inputs back to the always-on environment.

## Measured capability

Real throughput, elapsed-time, and memory numbers are treated as private and
local (see [ADR 0018](decisions/0018-benchmark-results-local-only.md) and
`docs/PUBLIC_PRIVATE_BOUNDARY.md`) — this table intentionally does not carry
them. The benchmark *method* stays public and reproducible:

- `make cluster-benchmark` (`infra/ansible/playbooks/benchmark.yml`): a
  small, dependency-free CPU/memory probe run independently per node, not the
  production Discogs parser.
- `make cluster-benchmark-distributed`: compares that same workload's
  aggregate throughput fanned out across the joined Pi workers via RQ against
  a single-node baseline.

Both write their results to `local/benchmarks/`, never into this file. See
`infra/ansible/README.md`'s "Benchmarking" section to reproduce a measurement
against your own hardware.
