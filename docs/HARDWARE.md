# Hardware context

The hardware is part of the learning story and may be documented publicly without exposing deployment identity.

## Current lab

| Hardware | Intended role | Important constraint |
| --- | --- | --- |
| ZimaBoard 832 with 1 TB NVMe | Always-on coordination, state, storage, and orchestration host | Modest x86 compute; state and recovery need care |
| Four Raspberry Pi 3B nodes | Bounded ARM64 workers | 1 GB RAM and 10/100 Ethernet per node |
| Existing five-port cluster switch | Fan-out to the four workers | Worker links remain limited by Pi hardware |
| Tenda SM105 five-port 2.5GbE switch | Connect eero Pro 6E, coordination host, and cluster uplink | Unmanaged; improves backbone and placement, not Pi link speed |
| ASRock X600 DeskMeet workstation | Optional ingest, builds, benchmarks, and expensive analysis | Must not become required for public availability |

## Public documentation rule

Naming the device models and explaining their constraints is acceptable. Do not publish real hostnames, addresses, MAC addresses, serial numbers, physical placement, port maps, tunnel configuration, or backup destinations.

## Design implications

- Pi jobs must fit comfortably within 1 GB RAM with explicit concurrency limits.
- Snapshot distribution should be incremental, checksummed, and infrequent enough for 100 Mbps worker links.
- The 2.5GbE backbone chiefly benefits the coordination host, uplink organization, future endpoints, and large transfers that do not terminate on a Pi 3B.
- Heavy full-catalog work can run on the workstation and publish compact immutable inputs back to the always-on environment.
