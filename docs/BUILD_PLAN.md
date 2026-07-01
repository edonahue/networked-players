# Build plan

## Purpose and relationship to the roadmap

`docs/ROADMAP.md` is the high-level, undated index of phases and direction. This
document is its companion: an ordered, package-level, checkbox task list from
today's real state through an MVP to a full production webapp. ROADMAP phases are
cited inline as `(ROADMAP N)`. A single ROADMAP phase can span multiple milestones
here when MVP only needs part of it — for example ROADMAP phase 3 spans Milestones
3–5 below, and phase 4 spans Milestones 7 and 11. This document does not replace or
edit ROADMAP's own checkboxes.

## Where things stand today

Snapshot as of 2026-07-01. This section is rewritten as work lands; the milestones
below are the durable structure. Every claim here has a source — do not extend it
without one, per AGENTS.md: do not claim an application, service, cluster
deployment, full dump conversion, benchmark, or public dataset exists until the
repository contains evidence for it.

**Catalog ingestion (`packages/catalog`).** Working and tested. The `manifest`,
`download`, `parse-releases`, and `validate` CLI commands are implemented and
covered by synthetic tests (`make check` green). The release parser streams gzip
XML into bounded Zstandard Parquet release/track/credit tables, preserving PAN/ANV
and evidence per `data/contracts/discogs-release-v2.md` (schema v2). Artists,
labels, and masters parsers remain intentionally deferred. No real Discogs dump has
been downloaded or parsed on real hardware yet, and — as of last night's bootstrap
session — a real attempt is currently expected to be infeasible on the coordination
host until its storage is expanded (see Infrastructure, below). No private seed has
been imported; no one-hop expansion and no artist graph exist yet, anywhere.

**Graph, game rules, workers, API (`packages/graph-core`, `packages/game-rules`,
`packages/workers`, `apps/api`).** Placeholders. Each has only a README describing
planned responsibility. No source code exists in any of them.

**Web application (`apps/web`).** Early implementation. A static Astro site with
`/`, `/about/`, and `/demo/` pages, dark/light theme, and SEO basics. The demo
renders 2–3 curated paths from a synthetic, privacy-safe artifact
(`public/data/challenge.v1.json`) shaped to match the real credits schema so a real
artifact can drop in later without code changes. Deploy configuration
(`wrangler.jsonc`) targets `networked-players.com`, but `npm run deploy` has not
been run — nothing is live at the domain yet. The coordination host's Node
mismatch (Node 20.20.2 vs. `package.json`'s `>=22` requirement) blocked local
dev/test until `scripts/setup-node-playwright.sh` installed Node 22 via `nvm`
plus Playwright's Chromium and Debian system deps; `.github/workflows/web.yml`
now runs format check, Astro check/build, and the Playwright smoke test on every
pull request and push to `main`.

**Infrastructure and hardware (`infra/`).** Real bring-up began the night of
2026-06-30/07-01 and has continued since. Per
[ADR 0007](decisions/0007-zimaboard-swarm-manager.md): the ZimaBoard 832
coordination host has Docker Engine installed, and Docker Swarm was initialized on
it — it is now an independently verifiable single-manager Swarm (`docker info`
reports `Swarm: active`, `Is Manager: true`). A worker join token was captured to
local, git-ignored storage (`local/swarm/`) so joining a Pi later is a one-line
operation. Portainer CE now runs alongside it as a plain (non-Swarm) container for
Swarm visibility, bound to the host's Tailscale IP rather than a loopback-only SSH
tunnel ([ADR 0008](decisions/0008-portainer-swarm-visibility.md), revised by
[ADR 0009](decisions/0009-portainer-tailscale-access.md)); Tailscale itself was
installed and this host joined to the operator's tailnet
(`scripts/install-tailscale.sh`). The GitHub CLI (`gh`) was installed for
persistent, tunnel-friendly GitHub authentication (`scripts/install-gh-cli.sh`),
and a standalone DuckDB CLI was installed for inspecting Parquet/DuckDB output
directly on the host (`scripts/install-duckdb-cli.sh`, since the `duckdb` Python
package ships no CLI entry point). However: **the four Raspberry Pi 3B workers are
not yet provisioned** (not flashed, not joined — the token is just waiting for
them). The coordination Postgres/Redis compose stack described in
`infra/swarm/docker-compose.coordination.yml`, originally deferred by ADR 0007
pending the NVMe, is now **running** — brought up ahead of the NVMe via the new
`infra/swarm/deploy-coordination.sh` once the eMMC's real headroom recovered (see
below); see
[ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md). A local,
git-ignored Ansible inventory now exists, and tooling to run the read-only health
playbook locally was added (`infra/ansible/run-health-local.sh`), but a full pass
has not been achieved: the playbook's free-space assertion has not been re-run
against the recovered headroom this session, so its outcome remains unverified.

**The current hard blocker — narrower than it was.** The coordination host's eMMC
root filesystem (28 GB) was at 97% full (817 MB free) as of the ADR 0007
bootstrap session, with no NVMe attached. As of this session, `df` shows the eMMC
with roughly 11.5 GB free — real, verified headroom recovered without the NVMe
ever having been attached; the cause of that recovery was not diagnosed this
session. An NVMe install remains planned. Until it's attached and the local data
root is fully relocated onto it, the host still cannot satisfy the ~250 GB ingest
floor in `docs/DATA_SIZING.md`, and the guarded pre-flight script
(`scripts/check-ingest-feasibility.sh`, wired to `make ingest-check`) is still
expected to defer any real bulk-ingestion attempt (Milestone 3) until then. That
250 GB floor, however, was never a requirement for the two lightweight, bounded
Postgres/Redis containers — per
[ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md), the recovered
headroom is judged sufficient for those specifically, and they are now running on
the eMMC ahead of the NVMe, with a known migration obligation once it lands (see
ADR 0010's revisit trigger).

**Hardware.** One ZimaBoard 832 coordination host: OS flashed and confirmed
64-bit; Docker Swarm manager active; storage expansion (NVMe) pending. Four
Raspberry Pi 3B workers (1 GB RAM, ARM64) are planned per `docs/HARDWARE.md` but not
yet provisioned. One optional workstation-class build node remains outside the
uptime contract per architecture direction.

| Area | State |
| --- | --- |
| Discogs release ingestion (code) | Working, tested, synthetic-only |
| Discogs release ingestion (real run) | Not attempted; currently infeasible (storage) |
| Private seed import | Not implemented; operator's private export is ready — Milestone 4 not yet scoped |
| One-hop graph expansion | Not implemented |
| `graph-core` | Placeholder (README only) |
| `game-rules` | Placeholder (README only) |
| `workers` | Placeholder (README only) |
| `apps/api` | Placeholder (README only) |
| `apps/web` | Early implementation, synthetic demo, not deployed; Node 22 + Playwright fixed locally, CI added |
| Coordination host OS + inventory | Done (64-bit confirmed, local inventory created) |
| Coordination host storage | eMMC headroom recovered (~11.5 GB free); NVMe still not attached; 250 GB bulk-ingest floor still unmet |
| Docker Swarm manager | Active (ADR 0007) |
| Worker join token | Captured locally, unused |
| Portainer | Running (ADR 0008), Tailscale-bound (ADR 0009) |
| Tailscale (coordination host) | Installed, connected to operator's tailnet |
| Coordination compose (Postgres/Redis) | Running (ADR 0010), brought up ahead of NVMe; loopback-bound |
| DuckDB CLI (host) | Installed (`scripts/install-duckdb-cli.sh`) |
| GitHub CLI (`gh`, host) | Installed (`scripts/install-gh-cli.sh`) |
| `apps/web` CI | Added (`.github/workflows/web.yml`): format/check/build/Playwright smoke |
| Health playbook | Runnable locally; free-space check expected to fail |
| Raspberry Pi workers | Not yet provisioned |
| `networked-players.com` | Registered, not live |

## How to use this document

Checkboxes are advisory, not contractual. Update "Where things stand today" whenever
a milestone task lands for real — cite the commit or ADR, don't just tick the box.
File the ADR a milestone flags at the time that decision is actually made, not
in advance. Don't reorder completed milestones; add follow-up milestones at the end
of a track if scope grows.

## Milestone 1: Verify and unblock the coordination host (ROADMAP 1)

### Goal
Resolve the current storage blocker and get a full, passing health check on the
real host before it carries any more ingestion or Swarm-manager weight. (The
coordination Postgres/Redis stack no longer waits on this milestone — it was
brought up ahead of the NVMe per
[ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md); this milestone
still gates Milestone 3's bulk ingest, which needs the full 250 GB floor.)

### Depends on
Nothing outstanding — this is the current critical path.

### Tasks
- [ ] Attach the NVMe and relocate the local data root off the eMMC (Postgres/Redis
      volumes — now live and must be migrated, not recreated, per
      [ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md) — plus
      `local/raw/`, `local/processed/`) — the explicit next step named in
      [ADR 0007](decisions/0007-zimaboard-swarm-manager.md)'s revisit trigger
      [`infra/`]
- [ ] Set a revised free-space floor for the coordination host's Ansible
      `host_vars` reflecting the new mount [`infra/ansible`]
- [ ] Re-run `./infra/ansible/run-health-local.sh` and confirm the free-space
      assertion passes [`infra/ansible`]
- [ ] Write and locally test coordination-host recovery notes (state backup /
      restore path for the eventual compose-managed Postgres + Redis volumes)
      [`infra/`, local-only notes]

## Milestone 2: Finish Swarm bring-up on real hardware (ROADMAP 2)

### Goal
Complete cluster bring-up: the manager is already live; provision and join the
four Pi workers. Independent of Milestones 3–9 (the data/graph track) — can
proceed in parallel with them. The coordination Postgres/Redis stack (see Tasks
below) no longer waits on Milestone 1's NVMe work — per
[ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md), the recovered
eMMC headroom is judged sufficient for those two lightweight containers, distinct
from the 250 GB bulk-ingest floor Milestone 3 still needs. This milestone's
sessions also picked up host tooling (Portainer, Tailscale, Node/Playwright,
DuckDB CLI, `apps/web` CI, GitHub CLI) that isn't strictly Swarm-specific; folded
in below as its own block rather than a new milestone, per current decision.

### Depends on
Nothing outstanding for the tasks below. The compose-stack task no longer depends
on Milestone 1 (see ADR 0010); Pi provisioning was never gated by it.

### Tasks
- [x] Initialize a single-manager Swarm on the coordination host — done, see
      [ADR 0007](decisions/0007-zimaboard-swarm-manager.md)
- [x] Capture a worker join token to local, git-ignored storage — done
      (`local/swarm/`)
- [ ] Flash a 64-bit OS to each of the four Raspberry Pi workers and confirm
      architecture (they are not yet provisioned)
- [ ] Join each Pi worker using the saved token as it becomes available
      [`infra/swarm`]
- [ ] Confirm `docker node ls` shows the manager plus all four workers
- [ ] Deploy the harmless multi-arch smoke service (`traefik/whoami`, global mode)
      and confirm placement on each worker via `docker service ps` [`infra/swarm`]
- [ ] Remove the smoke service; drain, remove, and rejoin one worker as a recovery
      drill, confirming it rejoins cleanly [`infra/swarm`]
- [x] Bring up `docker-compose.coordination.yml` (Postgres 17 + Redis 7-alpine) —
      done ahead of Milestone 1/NVMe, using recovered eMMC headroom, via
      `infra/swarm/deploy-coordination.sh`; see
      [ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md). Both
      services are loopback-bound (confirmed via `ss -tln`) and pinned to the
      manager simply by running as a plain `docker compose` container here, not
      a Swarm service — there is no Swarm placement constraint to confirm, since
      this was never designed as a Swarm stack [`infra/swarm`]
- [ ] Back up manager state (Swarm CA/raft) and locally test its recovery
      procedure

### Host tooling (this session, folded into this milestone)
- [x] Deploy Portainer CE as a plain (non-Swarm) container for Swarm visibility,
      bound to the coordination host's Tailscale IP — see
      [ADR 0008](decisions/0008-portainer-swarm-visibility.md) and
      [ADR 0009](decisions/0009-portainer-tailscale-access.md) [`infra/swarm`]
- [x] Install Tailscale on the coordination host and join it to the operator's
      tailnet (`scripts/install-tailscale.sh`) — see ADR 0009
- [x] Fix `apps/web`'s Node version mismatch (host had Node 20.20.2;
      `package.json` requires `>=22`) and install Playwright's Chromium plus
      Debian system deps via `scripts/setup-node-playwright.sh`
- [x] Install a standalone DuckDB CLI via `scripts/install-duckdb-cli.sh` (the
      `duckdb` Python package ships no CLI entry point)
- [x] Add `.github/workflows/web.yml` to validate `apps/web` (format check,
      Astro check/build, Playwright smoke test) on pull requests and pushes to
      `main`
- [x] Install the GitHub CLI (`gh`) via `scripts/install-gh-cli.sh` for
      persistent, tunneling-friendly GitHub authentication from the coordination
      host

## Milestone 3: Real ingestion dry run (ROADMAP 3)

### Goal
Prove the existing, tested catalog pipeline against a real Discogs snapshot on real
hardware — the prerequisite for every later graph milestone.

### Depends on
Milestone 1's NVMe relocation. `scripts/check-ingest-feasibility.sh` is expected to
defer this milestone until then.

### Tasks
- [ ] Run `make ingest-check` (wraps `scripts/check-ingest-feasibility.sh`) and
      confirm it reports enough free space before attempting anything real
      [`scripts/`]
- [ ] Obtain a real monthly snapshot manifest and confirm the object URL resolves
      [`packages/catalog`]
- [ ] Run a bounded `MAX_RELEASES` slice end to end (`make ingest`) and record
      observed elapsed time, peak memory, and input/output bytes per
      `docs/OPERATOR_SETUP.md`'s "Measure each run" [`packages/catalog`,
      `docs/DATA_SIZING.md`]
- [ ] Run `validate` against the resulting dataset and confirm DuckDB invariants
      hold on real (not synthetic) data [`packages/catalog`]
- [ ] Decide, from the measured slice, whether a full unbounded parse is
      coordination-host-feasible or workstation-only; update
      `docs/DATA_SIZING.md` with observed (not projected) figures

## Milestone 4: Private seed import (ROADMAP 3)

### Goal
Build the missing mechanism that turns the user's private Discogs Spinner export
into a local, never-published release-ID seed the pipeline can consume.

**Status note (flag only, not scoped here):** the operator's private Discogs
collection export is ready (or nearly ready) as of this session — this milestone
is well-motivated to start as soon as Milestone 3 lands a real dataset to select
from. Its seed-input contract, import mechanism, and ADR are intentionally left
fully unscoped by this note; see Tasks and "Possible ADR" below for what's still
undecided.

### Depends on
Milestone 3 (a real normalized release/credit dataset to select from).

### Tasks
- [ ] Define the smallest seed input contract (e.g. a flat release-ID list) and
      where it lives under the git-ignored `local/` tree [`packages/catalog`,
      `docs/DISCOGS_INGESTION.md`]
- [ ] Implement a seed-import command or module that reduces a local export to
      release IDs only, rejecting any account-linked fields [`packages/catalog`]
- [ ] Add synthetic seed fixtures under `data/samples/` that exercise the import
      contract without reproducing real collection membership [`data/samples`]
- [ ] Add tests: valid seed, malformed seed, seed IDs absent from the current
      snapshot, empty seed [`packages/catalog`]
- [ ] Confirm no seed-derived file this milestone touches is committable (extend
      `.gitignore` coverage if a new local path is introduced)

### Possible ADR
The seed input format and import mechanism is a "durable contract" per ROADMAP 4
and a candidate settled direction under AGENTS.md — record an ADR once the
contract is chosen. (Don't pre-assign a number; the next available one is
whatever hasn't been used when this actually lands — six exist as of this writing,
0007 was just taken by the Swarm-manager bootstrap.)

## Milestone 5: One-hop catalog expansion (ROADMAP 3)

### Goal
Turn the seed's release IDs plus the real dataset into the frontier-and-filter
one-hop expansion `docs/DISCOGS_INGESTION.md` already describes, producing the
smallest real graph-ready corpus.

### Depends on
Milestones 3 and 4.

### Tasks
- [ ] Extract the seed releases' linked credited-artist IDs into an artist-ID
      frontier [`packages/catalog`]
- [ ] Scan the release table to retain releases containing a frontier artist
      [`packages/catalog`]
- [ ] Preserve every retained release and credit row needed to prove each edge —
      no shortcut that drops evidence [`packages/catalog`]
- [ ] Write the expanded slice as its own versioned, immutable dataset (do not
      mutate the snapshot in place) [`packages/catalog`]
- [ ] Add a test asserting the expansion is deterministic and bounded given a
      fixed seed and snapshot [`packages/catalog`]

**Caveat, stated plainly rather than resolved in advance:** a bounded slice from
Milestone 3 may prove insufficient to build the release→artist index this
expansion needs — the full sequential parse might be required first. Decide once
Milestone 3's real results are in; see Sequencing notes below.

## Milestone 6: Minimal graph-core (ROADMAP 4, 5)

### Goal
Replace the `graph-core` placeholder with the smallest correctness-first
implementation capable of one-hop traversal and evidence-preserving path
reconstruction.

### Depends on
Milestone 5.

### Tasks
- [ ] Choose and implement a small readable fixture representation (e.g. NetworkX
      or an equivalent adjacency structure) as the correctness oracle
      [`packages/graph-core`]
- [ ] Load the artist–release bipartite graph from the one-hop Parquet output,
      preserving release/credit evidence on each edge [`packages/graph-core`]
- [ ] Implement path lookup between two artist nodes that returns the underlying
      release/credit evidence for every hop, not just artist names
      [`packages/graph-core`]
- [ ] Add tests against small synthetic fixtures under `data/samples/`: a direct
      one-hop path, a non-linked contributor correctly excluded from playable
      nodes, and a missing/absent path [`packages/graph-core`, `data/samples`]
- [ ] Manually verify at least one real evidence path from the actual one-hop
      expansion end to end (not just against synthetic fixtures)

### Possible ADR
A lightweight ADR for the *initial* graph representation choice is worth recording
now, separate from the later ROADMAP-7 benchmark gate that selects the
optimized/compact production representation — this keeps "selected only after
measurement" honest about which decision is provisional.

## Milestone 7: Static artifact + graph-snapshot contract (ROADMAP 4)

### Goal
Define the versioned contracts a real challenge artifact needs before generating
one, so this isn't improvised inside `apps/web`.

### Depends on
Milestone 6.

### Tasks
- [ ] Define and document a graph-snapshot contract (version, source dataset
      snapshot, generation method, evidence fields retained), likely
      `data/contracts/graph-snapshot-v1.md` [`data/contracts/`]
- [ ] Define and document the static-challenge artifact contract, matching the
      shape `apps/web`'s synthetic `challenge.v1.json` already anticipates
      [`data/contracts/`]
- [ ] Confirm the contract records required provenance per
      `docs/DATA_AND_RIGHTS.md` (source, snapshot date, schema/parser versions,
      omitted fields)

## Milestone 8: Generate and swap in the real challenge (ROADMAP 5)

### Goal
Produce one real, privacy-safe, evidence-backed challenge from the actual one-hop
graph and replace the synthetic demo artifact in `apps/web` — the functional core
of the MVP.

### Depends on
Milestones 6 and 7.

### Tasks
- [ ] Generate one real challenge artifact from the manually verified path
      (Milestone 6) using the contracts from Milestone 7 [`packages/graph-core`,
      `data/`]
- [ ] Confirm the generated artifact contains no collection-membership signal
      beyond derived public catalog facts, per
      `docs/PUBLIC_PRIVATE_BOUNDARY.md`'s pre-publish checklist
- [ ] Replace `apps/web/public/data/challenge.v1.json`'s synthetic content with
      the real generated artifact, keeping the schema unchanged [`apps/web`]
- [ ] Confirm the demo page renders correctly against the real artifact with no
      code changes required [`apps/web`]
- [ ] Update `apps/web/README.md`'s "Next steps" section to reflect the swap

## Milestone 9: First deploy to networked-players.com (ROADMAP 5)

### Goal
Make the real, one-hop, evidence-backed demo the live public experience.

### Depends on
Milestone 8.

### Tasks
- [ ] Confirm domain control, HTTPS, and static asset delivery independently of
      the home lab, per ADR 0004's validation step
- [ ] Run `npm run deploy` (`astro build && wrangler deploy`) [`apps/web`]
- [ ] Confirm the deployed site works with all home-hosted services disabled
      (static-first check per ADR 0002 and `docs/PRODUCT.md`)
- [ ] Update `README.md`'s status line and `docs/PRODUCT.md`'s identity paragraph
      to reflect that a real application is live — only once it actually is

## Milestone 10: MVP checkpoint

### Goal
Confirm all MVP conditions are simultaneously true. A checkpoint, not new
implementation work.

### Depends on
Milestone 2 and Milestones 3–9, all complete.

### Tasks
- [ ] A real one-hop artist-credit graph, derived from the private seed, is live
      at `networked-players.com` (not synthetic)
- [ ] The private seed itself was never committed or published; only derived
      catalog facts with provenance were
- [ ] Docker Swarm is initialized with all four Pi workers joined and verified (no
      worker job needs to be running yet)
- [ ] `docs/ROADMAP.md` phases 0, 1, 2, 3, and 5 reflect real completed checkboxes
- [ ] Update "Where things stand today" above to record MVP reached, dated

---

## Production (post-MVP)

## Milestone 11: Durable contracts and expanded evidence coverage (ROADMAP 4, 6)

### Goal
Move past the one-hop MVP slice toward a broader, still-measured graph, now that a
real end-to-end path exists to validate against.

### Depends on
Milestone 10.

### Tasks
- [ ] Version normalized artist, master, and label schemas as those parsers are
      added [`packages/catalog`, `data/contracts/`]
- [ ] Define a role taxonomy while preserving original role text
      [`packages/catalog`, `data/contracts/`]
- [ ] Define snapshot retention, free-space guardrails, and recovery automation
      beyond the manual steps in `docs/OPERATOR_SETUP.md` [`docs/`, `infra/`]
- [ ] Add repeatable worker jobs over immutable partitions — the first real
      `packages/workers` code, replacing its placeholder README
      [`packages/workers`]
- [ ] Measure snapshot size, transfer, memory, and execution limits on each
      hardware class (coordination host, Pi, optional workstation)
      [`docs/DATA_SIZING.md`]

### Possible ADR
Likely warranted once `packages/workers` picks a real queue/execution mechanism
(Redis/RQ is the stated default direction in `docs/ARCHITECTURE.md`; committing to
it in code is a settled-direction change).

## Milestone 12: Graph benchmark gate (ROADMAP 7)

### Goal
Select the production graph representation only after measuring the fixture-based
`graph-core` implementation against at least one optimized alternative.

### Depends on
Milestone 11.

### Tasks
- [ ] Keep the Milestone 6 fixtures as the correctness oracle throughout
- [ ] Compare compact arrays or an optimized graph library against the fixture
      implementation on real hardware [`packages/graph-core`]
- [ ] Record hardware, dataset version, method, and results — no unsupported
      performance claims [`docs/`]
- [ ] Select and implement the production representation based on the
      measurement [`packages/graph-core`]

### Possible ADR
Required by ROADMAP 7's own language ("select the production representation only
after measurement") — the clearest pre-flagged ADR point in this whole plan.

## Milestone 13: Game rules and richer challenges (ROADMAP 5, 6)

### Goal
Replace the `game-rules` placeholder with real challenge definition, validation,
scoring, and explainable-path logic, independent of any web framework.

### Depends on
Milestone 12 (could start earlier against the Milestone 6 fixture graph if
desired, but full challenge variety needs broader coverage).

### Tasks
- [ ] Define challenge and answer-validation logic against a static graph
      snapshot, no live search required [`packages/game-rules`]
- [ ] Implement scoring and hint logic [`packages/game-rules`]
- [ ] Implement explainable path presentation (the evidence-per-hop explanation
      already promised in `docs/PRODUCT.md`) [`packages/game-rules`]
- [ ] Wire `apps/web` to consume `game-rules` output instead of ad hoc demo logic
      [`apps/web`, `packages/game-rules`]
- [ ] Expand challenge generation and publish broader public findings
      [`packages/workers`, `packages/game-rules`]

## Milestone 14: Bounded live API (ROADMAP 9)

### Goal
Replace the `apps/api` placeholder with a bounded, rate-limited search/challenge
API that degrades gracefully — strictly additive to the static-first core.

### Depends on
Milestones 12 and 13.

### Tasks
- [ ] Define bounded request/response contracts, snapshot version behavior, and
      evidence response shape [`apps/api`, `docs/`]
- [ ] Add caching, rate limiting, validation, and observability [`apps/api`]
- [ ] Review exposure and failure behavior — confirm collection membership,
      internal infrastructure identity, and unrestricted graph traversal are
      never exposed, per `apps/api/README.md`'s hard rule
- [ ] Confirm static use remains fully available during an API outage (the
      static-first contract from ADR 0002 still holds)
- [ ] Deploy the API and update `apps/web` to use it as an additive enhancement

## Milestone 15: Full initial production webapp

### Goal
Broader graph coverage, real worker jobs running on the joined Pi swarm, a live
bounded API, and selected later-possibilities features from `docs/PRODUCT.md`.

### Depends on
Milestones 2, 11, 12, 13, and 14, all complete.

### Tasks
- [ ] Run real worker jobs (validation, challenge generation, score calculation,
      path batches) on the joined Pi workers, not just the Milestone 2 smoke
      service [`packages/workers`, `infra/swarm`]
- [ ] Parse all required dump types (artists, masters, labels) within acceptable
      resource limits [`packages/catalog`]
- [ ] Produce compact versioned publication artifacts with demonstrated
      reproducible rebuild and rollback [`packages/catalog`, `packages/graph-core`]
- [ ] Select and implement later-possibilities features from `docs/PRODUCT.md`
      (daily/curated paths, hidden contributor, role-restricted paths, shortest
      documented route, collection-inspired challenges using derived public
      facts) [`packages/game-rules`, `apps/web`]
- [ ] Confirm the optional workstation-class node remains outside the public
      uptime contract throughout
- [ ] Update `README.md`, `docs/PRODUCT.md`, and `docs/ROADMAP.md` checkboxes to
      reflect the production state reached

---

## Sequencing notes

- **Milestone 3 → 5 dependency may bounce back.** `docs/DISCOGS_INGESTION.md`
  notes the first full sequential parse may still be needed to build a reusable
  release-to-artist index, even though Milestone 3 only asks for a bounded slice.
  If Milestone 5 can't build its frontier from a bounded slice, Milestone 3 may
  need to be redone as a full parse first. Don't treat this as resolved until
  Milestone 3's real results are in.
- **The NVMe relocation is tonight's real critical-path discovery, not a
  hypothetical.** Per [ADR 0007](decisions/0007-zimaboard-swarm-manager.md), the
  coordination host's eMMC was at 97% full with no NVMe attached during the first
  bootstrap session — this is why Milestone 1 gates Milestone 3 (ingestion). It no
  longer gates any part of Milestone 2: the coordination compose stack was brought
  up ahead of the NVMe once the eMMC's real headroom recovered, per
  [ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md) — see "Where
  things stand today" above. Revisit ADR 0007 itself once the NVMe is attached;
  its own revisit trigger names this exact moment.
- **ADR triggers flagged in this document are not self-enforcing.** Confirm the
  corresponding ADR actually got filed when a flagged milestone lands — don't
  pre-assign ADR numbers here, since unrelated work (like ADR 0007) can take the
  next number first, as it just did.
