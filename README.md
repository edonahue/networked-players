# Networked Players

**Networked Players** is an open, evidence-first music-credit graph project and game. It explores the people who connect recorded music: performers, writers, producers, engineers, arrangers, designers, and other credited contributors.

The project begins with a private collection-derived seed, expands through adjacent catalog credits, and produces documented paths between artists and releases. The first public experience will be static-first so it remains useful even when the home lab is offline.

> **Status:** planning and repository scaffolding. No working application, API, data pipeline, or cluster deployment is claimed yet.

## Project identity

- **Project and product name:** Networked Players
- **Future canonical domain:** `networked-players.com` — registered and reserved for the eventual public website and game
- **Source and project history:** this repository
- **Learning companion:** the Music-Credit Graph Study Lab

No application is deployed at the domain yet. Until the first public experience exists, the repository and study lab remain the active references.

## Study companion

The design grew out of the [Music-Credit Graph Study Lab](https://lab.erichdonahue.com/projects/music-graph-study/) on [Erich's Lab](https://lab.erichdonahue.com/). The lab remains a learning artifact; this repository owns the actual Networked Players product, data, application, and infrastructure work.

## Product direction

The smallest useful public experience is a playable, evidence-backed challenge:

1. Present two artists or releases.
2. Reveal or ask the player to find a path through credited work.
3. Preserve the release-level evidence for every step.
4. Explain why each connection exists.
5. Continue to work from a static artifact when live services are unavailable.

Later possibilities include bounded artist-to-artist search, daily challenges, hidden contributors, role constraints, collection-inspired challenges, and visual exploration of collaboration networks.

## Planned architecture

The current design is intentionally modest and recoverable:

- **Coordination and state:** one SSD-backed x86 host for configuration control, orchestration management, durable services, and canonical snapshots.
- **Workers:** four Raspberry Pi 3B nodes for bounded ARM64 jobs against immutable, versioned inputs.
- **Optional heavy compute:** a workstation-class machine for full ingest, compaction, image builds, benchmarks, and expensive analysis without becoming part of the public uptime contract.
- **Data:** versioned Parquet for analytical records, DuckDB for transforms and validation, PostgreSQL for mutable application state, and Redis/RQ for operational background jobs.
- **Graph:** an evidence-bearing artist–release bipartite model, with simpler fixtures as correctness oracles and compact representations selected only after measurement.
- **Delivery:** static challenges and findings first; a bounded live API later.

These are selected directions, not completed implementation.

## Repository map

```text
apps/                Future user-facing web and API applications
packages/            Catalog, graph, game-rule, and worker packages
data/                 Public schemas, contracts, and synthetic fixtures
docs/                 Product, architecture, rights, safety, and decisions
infra/                Reproducible Ansible and Docker Swarm scaffolding
tests/                Future cross-project validation and acceptance tests
local/                Ignored machine-specific working area
```

## Public by default, private by necessity

This repository is public for learning, reproducibility, and honest project development. It may document hardware classes and selected components when they materially explain a constraint. It must not expose the identity or access path of the running environment.

Never commit:

- credentials, tokens, keys, cookies, or real environment files;
- internal or public addresses, real hostnames, MAC addresses, serial numbers, or DHCP reservations;
- tunnel identifiers, firewall mappings, remote-access details, or production inventory files;
- private collection exports, collection membership, database dumps, or personal account data;
- backup destinations, restore credentials, production logs, or incident details that increase attack surface.

Safe examples use synthetic data and placeholder identities. See [Public and private boundaries](docs/PUBLIC_PRIVATE_BOUNDARY.md) and [Security](SECURITY.md).

## First vertical slice

The first implementation milestone should prove one complete path rather than many disconnected components:

```text
private local collection slice
→ normalized credit records
→ one-hop catalog expansion
→ versioned analytical files
→ evidence-preserving graph
→ one manually verified artist path
→ static challenge artifact
→ small playable browser experience
```

The cluster is useful only when it advances this path or teaches a clearly documented distributed-systems lesson.

## Project principles

- **Evidence before inference.** A documented credit proves participation or collaboration, not artistic influence.
- **Static before always-on.** The public experience must degrade gracefully when the home lab is unavailable.
- **Measure before optimizing.** Compact arrays, distributed execution, and specialized graph technology must earn their complexity through benchmarks.
- **Open design, private identity.** Publish reusable code and decisions without publishing secrets or personal data.
- **Small hardware, bounded jobs.** Work must respect the Raspberry Pi 3B's memory, CPU, and network limits.
- **Rebuildable state.** Configuration, data contracts, and versioned artifacts should make recovery understandable.

## Contributing

This is currently a personal learning and portfolio project, but constructive issues and discussion are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing changes.

## License

No open-source license has been selected yet. This repository is public for learning, documentation, and project transparency. All rights are reserved unless stated otherwise.
