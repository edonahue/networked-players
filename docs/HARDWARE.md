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
- The x86 worker is the fleet's actual joined, higher-capability compute node and is the
  default target for heavy jobs (parsing, one-hop expansion, RQ/Dask fleet work) that don't
  need to run directly on the coordination host; an optional workstation remains available
  for ad hoc or offline full-catalog work, publishing compact immutable inputs back to the
  always-on environment.

### Future: coordination spare-worker lane (not implemented)

Approved in principle, not yet built: the master/coordination host may later run a small,
capped, opt-in local-compute lane for bounded jobs that specifically benefit from local
dataset access (avoiding a network hop to the x86 worker). This is deliberately **not**
`x86_workers` membership, is **never** a promotion path for the x86 worker, and is **never**
general Swarm task placement on the coordination host — the coordination host stays
manager-only and workload-light by design. If built, it would be on-demand only (not a
standing service), with suggested (not yet configured) resource limits: 1 worker process, 1
thread, a ~2 GiB Dask memory limit, a systemd `MemoryMax` around 2500M, `CPUQuota` in the
100–150% range, and `Nice=15` so it never contends with the host's own coordination duties.
No code, playbook, or Compose service implements this today.

### Future: reconsider Pi dataset-caching scope (not decided)

Background, not a decision: [ADR 0024](decisions/0024-http-readonly-catalog-data-access.md)
and [ADR 0025](decisions/0025-worker-local-dataset-cache.md) restrict Pi workers to
caching only the bounded one-hop dataset (a 2 GiB guard in
`replicate-dataset-pi.yml`), never the full catalog — explicitly "even though disk space
alone wouldn't stop them" (ADR 0025), because at the time neither the Pi's real free
space nor the one-hop dataset's real size had been measured. Both are now known:

- Real Pi free space (`make cluster-health`, 2026-07-04): each of the three active Pi
  workers has roughly **46–47 GB free** on `/` — see `docs/DATA_SIZING.md`'s "Worker-local
  dataset cache, first real run" for the per-worker figures.
- The real one-hop dataset (`docs/DATA_SIZING.md`'s "One-hop expansion, first real run"):
  **868 MB** — comfortably small even against the Pi's 1 GB RAM class, let alone its disk.
  Even the full `discogs` dataset (6.6 GB) is a small fraction of a Pi's real headroom.

This is exactly the kind of "measured evidence from a real Pi workload" ADR 0025's own
Revisit trigger asks for before reconsidering the one-hop-only rule and its 2 GiB guard —
disk space specifically is no longer the constraint it looked like on paper. It is not
the only constraint, though: the Pi's 100 Mbps link (not disk) is what ADR 0024's
bounded-only policy was really protecting against, and 1 GB RAM still bounds what a Pi
can usefully *do* with a larger cached dataset, not just store. Any future change here
should weigh transfer time and RAM-bounded usefulness, not disk headroom alone. No code,
playbook, or guard value changes as a result of this note — it only records the
background for whoever revisits ADR 0025's trigger next.

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
