# Hardware context

The hardware is part of the learning story, but the public repository only needs enough detail to explain meaningful constraints.

## Current lab

| Hardware | Intended role | Important constraint |
| --- | --- | --- |
| Compact x86 coordination host (currently a ZimaBoard 832) | Always-on coordination, state, storage, and orchestration | Modest compute; state and recovery need care |
| Four Raspberry Pi 3B nodes | Bounded ARM64 workers | 1 GB RAM and 10/100 Ethernet per node |
| Existing five-port cluster switch | Fan-out to the four workers | Worker links remain limited by Pi hardware |
| Tenda SM105 five-port 2.5GbE switch | Connect the router, coordination host, and cluster uplink | Unmanaged; improves backbone and placement, not Pi link speed |
| Optional workstation-class build node (a second, stock ZimaBoard 832, no NVMe yet) | Ingest, builds, benchmarks, and expensive analysis | Must not become required for public availability; not a Swarm member (ADR 0015) |

## Public documentation rule

Hardware classes and selected models may be named when they explain a design constraint. Do not publish a complete personal-machine inventory, real hostnames, addresses, MAC addresses, serial numbers, physical placement, port maps, tunnel configuration, or backup destinations.

## Design implications

- Pi jobs must fit comfortably within 1 GB RAM with explicit concurrency limits.
- Snapshot distribution should be incremental, checksummed, and infrequent enough for 100 Mbps worker links.
- The 2.5GbE backbone chiefly benefits the coordination host, uplink organization, future endpoints, and large transfers that do not terminate on a Pi 3B.
- Heavy full-catalog work can run on an optional workstation and publish compact immutable inputs back to the always-on environment.
