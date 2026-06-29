# Networked Players

**Networked Players** is an open, evidence-first music-credit graph project and game. It explores the people who connect recorded music: performers, writers, producers, engineers, arrangers, designers, and other credited contributors.

The project begins with a private collection-derived seed, expands through adjacent catalog credits, and produces documented paths between artists and releases. The first public experience will be static-first so it remains useful even when the home lab is offline.

> **Status:** early implementation and repository scaffolding. A tested Discogs release-ingestion slice now exists; no deployed application, public API, full catalog, or cluster deployment is claimed yet.

## Project identity

- **Project and product name:** Networked Players
- **Eventual production game host:** `networked-players.com` — registered and reserved for the public game
- **Source and project history:** this repository
- **Learning companion:** the Music-Credit Graph Study Lab

No application is deployed at the domain yet. When the first public game is ready, `networked-players.com` will host the player-facing experience rather than merely redirecting to GitHub or the study lab.

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

## Discogs ingestion foundation

The first working vertical slice lives in `packages/catalog` and deliberately stops before pretending a full-catalog product exists. It can:

- create a versioned monthly manifest for Discogs artists, labels, masters, and releases dumps;
- resume and verify a large download with size and SHA-256 checks;
- stream release XML directly from gzip without writing expanded XML;
- normalize release, track, and credit evidence, including PAN/ANV and non-linked names;
- write bounded Zstandard Parquet parts with a dataset manifest;
- validate identity and evidence invariants with DuckDB.

The working parser covers the releases dump first because release- and track-level credits are the shortest path to the initial collection-plus-one-hop graph. See [Discogs ingestion](docs/DISCOGS_INGESTION.md), [data sizing](docs/DATA_SIZING.md), and the [catalog package](packages/catalog/README.md).

```bash
uv sync --extra dev
uv run pytest
```

Real dumps, account exports, generated catalogs, and local manifests remain outside Git.

## Planned architecture

The current design is intentionally modest and recoverable:

- **Coordination and state:** one SSD-backed x86 host for configuration control, orchestration management, durable services, canonical snapshots, and controlled downloads.
- **Workers:** four Raspberry Pi 3B nodes for bounded ARM64 jobs against immutable, versioned inputs—not full raw-dump parsing.
- **Optional heavy compute:** a workstation-class machine for full ingest, compaction, image builds, benchmarks, and expensive analysis without becoming part of the public uptime contract.
- **Data:** versioned Parquet for analytical records, DuckDB for transforms and validation, PostgreSQL for mutable application state, and Redis/RQ for operational background jobs.
- **Graph:** an evidence-bearing artist–release bipartite model, with simpler fixtures as correctness oracles and compact representations selected only after measurement.
- **Delivery:** static challenges and findings first; a bounded live API later.

These are selected directions, not completed deployment.

## Repository map

```text
apps/                Future user-facing web and API applications
packages/            Catalog, graph, game-rule, and worker packages
data/                 Public schemas, contracts, and synthetic fixtures
docs/                 Product, architecture, rights, sizing, and decisions
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
- raw Discogs dumps or generated full-catalog artifacts;
- backup destinations, restore credentials, production logs, or incident details that increase attack surface.

Safe examples use synthetic data and placeholder identities. See [Public and private boundaries](docs/PUBLIC_PRIVATE_BOUNDARY.md) and [Security](SECURITY.md).

## First vertical slice

```text
private local collection slice
→ verified Discogs snapshot manifest
→ streaming release and credit normalization
→ versioned Parquet and DuckDB checks
→ one-hop catalog expansion
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
- **Rebuildable state.** Configuration, data contracts, checksummed inputs, and versioned artifacts should make recovery understandable.

## Contributing

This is currently a personal learning and portfolio project, but constructive issues and discussion are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing changes.

## License

No open-source license has been selected yet. This repository is public for learning, documentation, and project transparency. All rights are reserved unless stated otherwise.
