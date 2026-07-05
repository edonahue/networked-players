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

Snapshot as of 2026-07-02. This section is rewritten as work lands; the milestones
below are the durable structure. Every claim here has a source — do not extend it
without one, per AGENTS.md: do not claim an application, service, cluster
deployment, full dump conversion, benchmark, or public dataset exists until the
repository contains evidence for it.

**Catalog ingestion (`packages/catalog`).** Working and tested, and — as of
2026-07-01 — proven against real data on real hardware. The `manifest`, `download`,
`parse-releases`, and `validate` CLI commands are implemented and covered by
synthetic tests (`make check` green). The release parser streams gzip XML into
bounded Zstandard Parquet release/track/credit tables, preserving PAN/ANV and
evidence per `data/contracts/discogs-release-v2.md` (schema v2). Artists, labels,
and masters parsers remain intentionally deferred. A real bounded slice
(`MAX_RELEASES=10000`) of the June 2026 snapshot ran end to end on the coordination
host: real 11GB download (checksummed), 10,000 releases / 59,009 tracks / 91,202
credits parsed, `validate` reporting zero invariant violations — see
[Milestone 3](#milestone-3-real-ingestion-dry-run-roadmap-3) and
`docs/DATA_SIZING.md`'s "First real measurement." Discogs also moved public dump
hosting behind a Cloudflare proxy (`data.discogs.com`) with a different URL scheme
than the old direct-S3 path; `manifest.py` was updated accordingly. The operator's
real private seed was imported ([ADR 0011](decisions/0011-private-seed-contract.md));
no one-hop expansion and no artist graph exist yet (Milestone 5 is next). **Update,
2026-07-05: this is superseded** — one-hop expansion and graph-core are now both
implemented (Milestone 5, `expand-one-hop`) and the real run against the full dump
has completed (see the status table below and Milestone 5's own update). Later
the same day, real `cProfile` output on the parser (not the initially assumed
"decompression or Parquet writing" cause) found the actual bottleneck was
`releases.py` re-scanning each element's children once per field via repeated
`findtext()` calls; fixing it (a single child-text map built once per element) cut
measured parse time by **~1.9x**, and a bounded single-thread write/parse overlap
in `parquet.py` measured a further **~4.2%** — see `docs/DATA_SIZING.md`'s "Real
profiling" and "'Light' parallelism" sections. On the strength of that fix, a
**full, unbounded parse of the June 2026 snapshot was launched the same evening**
(2026-07-01 17:59:48 EDT, via the hardened supervised pipeline below) and **ran to
completion** (00:02:49 EDT, 2026-07-02, 6h 3m elapsed): **19,192,301 releases /
178,224,810 tracks / 220,015,758 credits**, 6.6 GB Parquet output, `validate`
reporting zero invariant violations at full scale — the first genuinely completed
full run, not a projection. See
[Milestone 3](#milestone-3-real-ingestion-dry-run-roadmap-3)'s last task and
`docs/DATA_SIZING.md`'s "Full unbounded run: complete" for the full numbers.
The next day, a real DuckDB profiling pass against the completed dataset
(`scripts/profile-discogs-dataset.sh`, `make profile-discogs` — reusable
against future snapshots) found two real bugs, both fixed: a
contract-documentation error (`master_is_main_release` was marked nullable
but never actually is — the raw dump always encodes "no master" with an
explicit `is_main_release="false"` attribute, so the parser's output was
already correct; only `data/contracts/discogs-release-v2.md` needed fixing)
and a small parser inconsistency (`status` wasn't empty-string-normalized
like every other text field — fixed with a test, zero effect on the
existing dataset). See `docs/discogs-data/raw-dump-schema.md`'s "Real
full-dataset profiling (2026-07-02)" for the full findings, including
confirmation that mojibake in 89 titles and other apparent oddities are
genuine, pre-existing source-data characteristics, not pipeline bugs.

**Game rules, workers, API (`packages/game-rules`, `packages/workers`,
`apps/api`).** Placeholders. Each has only a README describing planned
responsibility. No source code exists in any of them.

**Graph core (`packages/graph-core`).** **Update, 2026-07-04:** no longer a
placeholder. Implemented: a DuckDB-backed lazy `CreditGraph` (query-per-hop
BFS, never a materialized in-Python adjacency), the album-centered
`challenge.v2` artifact builder (`challenge.py`) with a leak-checking
`validate_challenge`, the medium-term proxy-ranking curation mechanism
(`analysis.py`), and a materialized co-credit graph-snapshot exporter
(`snapshot.py`) — 32 tests, all synthetic; no real-data run yet (live gates
B/F). See the status table below and `data/contracts/challenge-v2.md` /
`data/contracts/graph-snapshot-v1.md`.

**Web application (`apps/web`).** Early implementation. A static Astro site with
`/`, `/about/`, `/play/<album>/`, and `/demo/` pages, dark/light theme, and SEO
basics. As of this session the demo runs on **real Discogs data** — a small,
curated subset of releases and artist connections fetched via the Discogs API
against the operator's private seed, with cover art hotlinked directly from
Discogs' own CDN ([ADR 0012](decisions/0012-real-discogs-api-demo-challenge.md))
— a deliberate detour ahead of Milestone 8's dump-derived pipeline, not a
replacement for it. Deploy configuration (`wrangler.jsonc`) targets
`networked-players.com`; the operator deploys via their Cloudflare Git
integration on push to `main` rather than a manual `npm run deploy`. The
coordination host's Node mismatch (Node 20.20.2 vs. `package.json`'s `>=22`
requirement) blocked local dev/test until `scripts/setup-node-playwright.sh`
installed Node 22 via `nvm` plus Playwright's Chromium and Debian system deps;
`.github/workflows/web.yml` now runs format check, Astro check/build, and the
Playwright smoke test on every pull request and push to `main`. **Update,
2026-07-04:** the landing page was reframed around an album grid, with a new
`/play/<album>/` evidence-viewer page per album (find-the-connection /
reveal-the-path modes); this runs on real, working Astro code against a
**synthetic placeholder artifact** (`challenge.v2.json`, clearly marked as
such in its own provenance), not yet the real dump-derived data — the
original `/demo/` page above is unaffected and stays live, relabeled "Legacy
demo" in the nav.

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
package ships no CLI entry point). **Update, 2026-07-02:** three of the four
Raspberry Pi 3B workers (`worker-01`/`worker-02`/`worker-03`) are now
provisioned, onboarded, and joined to the Swarm for real — see "Fleet
bring-up" under Milestone 2 below for the full evidence. The fourth remains
unreachable, and the newly identified second ZimaBoard 832 (stock, no NVMe)
was, at the time, an optional build node not yet onboarded.
Onboarding tooling for both (`infra/ansible/playbooks/onboard.yml`,
[ADR 0015](decisions/0015-fleet-onboarding.md)) has now been run for real
against the three reachable Pi workers; the second ZimaBoard was still
untested. **Update, 2026-07-04: this is superseded** — the second
ZimaBoard has since joined the Swarm for real as a dedicated x86_64 worker
(`x86_workers`, [ADR 0022](decisions/0022-second-zimaboard-joins-as-x86-swarm-worker.md),
amending ADR 0015's original "optional build node, not a Swarm member"
framing) and now participates in the same RQ/Dask fleet work as the Pi
workers at a higher-capability tier ([ADR 0023](decisions/0023-x86-worker-joins-rq-dask-fleet-work.md)).
It is a genuine Swarm worker, never a manager, and remains a distinct host
from the master/coordination ZimaBoard described throughout this section.
Separately, the coordination
host itself was hardened the same day for safely running long, unattended
background jobs — persistent journald, a hardware watchdog, Docker log rotation,
and `vm.swappiness` tuning via `infra/ansible/playbooks/harden.yml`
([ADR 0014](decisions/0014-coordination-host-hardening.md)) — after real testing
surfaced two host-specific gotchas: `live-restore` is flatly incompatible with
Swarm mode (took `dockerd` down entirely until reverted), and
`restart: unless-stopped` alone did not bring the coordination stack back up after
a Docker daemon restart. A supervised-job pattern
(`scripts/run-ingest-supervised.sh`, `scripts/monitor-heavy-job.sh`) now runs heavy
ingestion as a resource-bounded (`Nice`, `IOSchedulingClass`, `MemoryMax`) systemd
transient unit with periodic progress logging, and an end-to-end ntfy.sh push
pipeline (`scripts/lib/notify.sh`, `scripts/install-run-and-ntfy.sh`, plus a
Claude Code hook pair for long ad hoc builds) notifies the operator on job
start/finish rather than requiring them to poll — verified end to end with real
notifications received. The coordination Postgres/Redis compose stack described in
`infra/swarm/docker-compose.coordination.yml`, originally deferred by ADR 0007
pending the NVMe, came up ahead of the NVMe via `infra/swarm/deploy-coordination.sh`
once the eMMC's real headroom recovered (see
[ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md)), and has since been
migrated onto the NVMe along with the rest of the local data root (see below). A
local, git-ignored Ansible inventory now exists; the read-only health playbook
(`infra/ansible/run-health-local.sh`) has been re-run against the real, mounted NVMe
and passes cleanly — no longer an unverified outcome. The next day, real
backup/restore tooling was added and live-tested for both remaining recovery
gaps ([ADR 0016](decisions/0016-state-backup-and-recovery.md)): the
coordination stack (`make backup-coordination`/`restore-coordination`, zero-
downtime `pg_dump`/Redis `BGSAVE`) round-tripped a real marker key through a
backup and restore, and the Swarm manager's CA/raft state (`make
backup-swarm-manager`) was backed up for real — Docker stopped, archived,
restarted, the coordination stack auto-redeployed, the manager confirmed
still healthy — with the archive's contents verified. This closes Milestone
1 outright and Milestone 2's last non-hardware-blocked task.

**Storage (`/mnt/data`).** The planned 1TB NVMe is now physically attached, wiped,
partitioned (ext4, one partition spanning the disk), and mounted at `/mnt/data`
(916G) — see [ADR 0013](decisions/0013-nvme-storage-layout.md). The repo's `local/`
directory is bind-mounted onto `/mnt/data/networked-players/local/` (revised from an
initial symlink approach after a `git rebase` was found to silently delete an
untracked symlink sitting where a previously-tracked file used to live — a bind mount
is immune to that failure mode, since `local/` stays a plain directory to git at every
point in its history). The coordination stack's `postgres-data`/`redis-data` Docker
volumes are migrated off the 28GB eMMC onto `/mnt/data/docker-volumes/`
(`infra/swarm/migrate-coordination-volumes-to-nvme.sh`), confirmed `Up (healthy)`
post-migration. The Ansible free-space floor now targets `/mnt/data` instead of the
eMMC root (`disk_floor_mount` in `infra/ansible/playbooks/health.yml`), and
`run-health-local.sh` reports **869.2 GB free** against the coordinator's 250GB floor
— a real, passing measurement, not a projection.

**The former hard blocker — now resolved.** The coordination host's eMMC root
filesystem (28 GB) was at 97% full (817 MB free) as of the ADR 0007 bootstrap
session, with no NVMe attached; it later recovered to roughly 11.5 GB free without
the NVMe ever having been attached (cause never diagnosed) and remains there today
— relocating `local/` didn't materially change eMMC headroom, since its prior
contents were tiny. What actually resolved the blocker is the NVMe itself: now
attached, mounted at `/mnt/data`, and holding the relocated data root (see
"Storage" above and [ADR 0013](decisions/0013-nvme-storage-layout.md)), the host
has **869.2 GB free** against `docs/DATA_SIZING.md`'s ~250 GB ingest floor —
confirmed via the Ansible health playbook, not projected. The guarded pre-flight
script (`scripts/check-ingest-feasibility.sh`, wired to `make ingest-check`) has
since been run for real against `SNAPSHOT=20260601` and passed — see
[Milestone 3](#milestone-3-real-ingestion-dry-run-roadmap-3)'s first task.

**Hardware, current state (updated 2026-07-04).** One master/coordination
ZimaBoard 832: OS flashed and confirmed 64-bit; Docker Swarm manager active;
1TB NVMe attached, mounted, and hardened for long-running jobs (see "Storage"
and "Infrastructure and hardware" above); authoritative home of
`local/processed/`; never a worker. A second, distinct ZimaBoard 832
(the "x86 worker," `x86_workers` group) is a real, joined, dedicated x86_64
Swarm worker ([ADR 0022](decisions/0022-second-zimaboard-joins-as-x86-swarm-worker.md)/
[ADR 0023](decisions/0023-x86-worker-joins-rq-dask-fleet-work.md)), worker-only
and never promoted to manager, participating in RQ/Dask fleet work at a
higher-capability tier than the Pi's. Three active Raspberry Pi 3B workers
(1 GB RAM, ARM64, `pi_workers`) are provisioned, onboarded, and joined; a
fourth original Pi, plus a separate Pi 3B+, are planned but not yet revived
— both would join `pi_workers` as Pi-class hardware when they are. See
`docs/HARDWARE.md` for the full table.

| Area | State |
| --- | --- |
| Discogs release ingestion (code) | Working, tested, synthetic-only; parser hot path fixed (~1.9x) and write/parse overlap added (~4.2%), 2026-07-01 |
| Discogs release ingestion (real run) | **Done at full scale.** Bounded 10,000-release slice (2026-07-01) and full unbounded parse (2026-07-01 17:59:48 → 2026-07-02 00:02:49 EDT, 19,192,301 releases) both validated clean — see Milestone 3 |
| Real dataset profiling | Done (2026-07-02): `scripts/profile-discogs-dataset.sh` / `make profile-discogs`; found and fixed 2 real bugs (1 contract-doc, 1 parser) — see `docs/discogs-data/raw-dump-schema.md` |
| Private seed import | Implemented (ADR 0011); operator's real seed imported locally |
| One-hop graph expansion | Implemented (`expand-one-hop`, Milestone 5); **real run done 2026-07-05** (gate B) — 1,410,106 releases, 868 MB, validated clean, after ADR 0026/0027's hub exclusions |
| `graph-core` | Implemented: DuckDB-backed lazy `CreditGraph`, challenge.v2 builder, proxy-ranking analysis, 32 tests, all synthetic; real-data run pending (live gate F) |
| Worker-local dataset caching | Implemented (ADR 0025): `dataset_fetch.py` puller/verifier, per-hardware-class ansible playbooks (x86 full/masters/one-hop, Pi one-hop-only + guard), rsync fallback, `resolve_dataset` resolution order. **Real run done 2026-07-05** (gate E): `discogs` (6.6GB, 11,517 files) rsync'd and `discogs-onehop` (868MB) HTTP-replicated to the x86 worker, both verified. Pi replication not yet attempted — see `docs/HARDWARE.md`'s "Future: reconsider Pi dataset-caching scope" |
| First real Pi production job | Implemented: challenge-evidence verification (`networked_players_graph_core.verify` + a self-contained RQ job body), sharded via `scripts/enqueue_verify_challenge.py`; real run against a Pi's cache pending (live gate G) |
| `game-rules` | Placeholder (README only) |
| `workers` | Placeholder (README only) |
| `apps/api` | Placeholder (README only) |
| `apps/web` | Early implementation; album-centered landing + `/play/<album>/` evidence viewer (real code, synthetic placeholder data pending live gate F), plus the ADR-0012 real curated `/demo/`; deploys via Cloudflare Git integration on push to `main`; Node 22 + Playwright (7 smoke tests) fixed locally, CI added |
| Coordination host OS + inventory | Done (64-bit confirmed, local inventory created) |
| Coordination host storage | NVMe attached and mounted at `/mnt/data` (916G ext4, ADR 0013); `local/` and coordination volumes relocated; 250 GB bulk-ingest floor met (869 GB free, confirmed) |
| Coordination host hardening | Done (ADR 0014): persistent journald, hardware watchdog, Docker log rotation, `vm.swappiness` tuning (`infra/ansible/playbooks/harden.yml`) |
| Supervised job + ntfy tooling | Added and verified end-to-end: resource-bounded `systemd-run` job wrapper, periodic progress monitor, ntfy.sh push notifications on start/finish |
| Docker Swarm manager | Active (ADR 0007) |
| Swarm manager state backup | Built and live-tested 2026-07-02 (ADR 0016); backup + integrity check confirmed, live restore untested by operator choice |
| Worker join token | Captured locally; used for real 2026-07-02 (3 of 4 workers joined) |
| Fleet onboarding tooling | Added (ADR 0015, `infra/ansible/playbooks/onboard.yml`); run for real 2026-07-02 against 3 Pi 3B workers |
| Guarded Swarm join automation | Added and used for real 2026-07-02 (ADR 0017, `infra/ansible/playbooks/swarm-join.yml`, `make cluster-swarm-join`) |
| Worker smoke test | Passed for real 2026-07-02 (`make cluster-smoke-test`), 3/3 currently-joined workers |
| One-worker recovery drill | Passed for real 2026-07-02 (drain/leave/remove/rejoin on `worker-01`) |
| Portainer | Running (ADR 0008), Tailscale-bound (ADR 0009) |
| Tailscale (coordination host) | Installed, connected to operator's tailnet |
| Coordination compose (Postgres/Redis) | Running (ADR 0010), brought up ahead of NVMe; loopback-bound. Backup/restore built and live-tested 2026-07-02 (ADR 0016) |
| DuckDB CLI (host) | Installed (`scripts/install-duckdb-cli.sh`) |
| GitHub CLI (`gh`, host) | Installed (`scripts/install-gh-cli.sh`) |
| `apps/web` CI | Added (`.github/workflows/web.yml`): format/check/build/Playwright smoke |
| Health playbook | Passing (confirmed 2026-07-01: 869.2 GB free on `/mnt/data`) |
| Raspberry Pi workers | **3 of 4 joined and smoke-tested, 2026-07-02** (ADR 0015, ADR 0017); fourth remains unreachable; a separate Pi 3B+ is also planned but not yet active |
| Second ZimaBoard 832 (the "x86 worker," `x86_workers`) | Joined as a real, dedicated x86_64 Swarm worker (ADR 0022/0023); worker-only, never promoted; participates in RQ/Dask fleet work at a higher-capability tier than the Pi's |
| `networked-players.com` | Registered, not live |

## How to use this document

Checkboxes are advisory, not contractual. Update "Where things stand today" whenever
a milestone task lands for real — cite the commit or ADR, don't just tick the box.
File the ADR a milestone flags at the time that decision is actually made, not
in advance. Don't reorder completed milestones; add follow-up milestones at the end
of a track if scope grows.

## Milestone 1: Verify and unblock the coordination host (ROADMAP 1)

**Done as of 2026-07-02** — every task below is complete, including a real,
live-tested backup/restore round-trip for the coordination stack.

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
- [x] Attach the NVMe and relocate the local data root off the eMMC (Postgres/Redis
      volumes — migrated via `infra/swarm/migrate-coordination-volumes-to-nvme.sh`,
      not recreated — plus `local/raw/`, `local/processed/` via a bind-mounted
      `local/`) — the explicit next step named in
      [ADR 0007](decisions/0007-zimaboard-swarm-manager.md)'s revisit trigger; see
      [ADR 0013](decisions/0013-nvme-storage-layout.md) [`infra/`]
- [x] Set a revised free-space floor for the coordination host's Ansible
      `host_vars` reflecting the new mount (`disk_floor_mount: /mnt/data`,
      `min_free_gb: 250`) [`infra/ansible`]
- [x] Re-run `./infra/ansible/run-health-local.sh` and confirm the free-space
      assertion passes — confirmed 2026-07-01, 869.2 GB free on `/mnt/data`
      [`infra/ansible`]
- [x] Write and locally test coordination-host recovery notes (state backup /
      restore path for the eventual compose-managed Postgres + Redis volumes)
      [`infra/`, local-only notes] — done 2026-07-02:
      `scripts/backup-coordination-stack.sh`/`restore-coordination-stack.sh`
      (`pg_dump` + Redis `BGSAVE`, no downtime, see
      [ADR 0016](decisions/0016-state-backup-and-recovery.md)), and a real
      round-trip tested live on the coordination host: set a Redis marker
      key, backed up, restored into the running stack, confirmed the marker
      key survived intact. Runbook in `docs/OPERATOR_SETUP.md`'s "Backup and
      recovery" section

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

Onboarding tooling now exists (`infra/ansible/playbooks/onboard.yml`, see
[ADR 0015](decisions/0015-fleet-onboarding.md)) to install Docker on each Pi and
print the real join command, but the tasks below stay unchecked — the tooling
hasn't been run against physical hardware yet, and this repo doesn't claim a task
done until there's evidence for it. **Update, 2026-07-04:** since run for real
against all three reachable Pi workers and, later, the second ZimaBoard (x86
worker) — see "Fleet bring-up" below, [ADR 0022](decisions/0022-second-zimaboard-joins-as-x86-swarm-worker.md),
and the status table.

### Tasks
- [x] Initialize a single-manager Swarm on the coordination host — done, see
      [ADR 0007](decisions/0007-zimaboard-swarm-manager.md)
- [x] Capture a worker join token to local, git-ignored storage — done
      (`local/swarm/`)
- [ ] Flash a 64-bit OS to each of the four Raspberry Pi workers and confirm
      architecture — **3 of 4 done as of 2026-07-02**: three Pi 3Bs (aarch64,
      Debian 12.14, confirmed via `make cluster-health`) are wired, reachable
      over Ethernet, and onboarded. The fourth (the former "Pi master") remains
      unreachable and is deliberately excluded from the active inventory rather
      than blocking the other three — see
      [ADR 0017](decisions/0017-guarded-swarm-worker-join-automation.md)
- [x] Join each Pi worker using the saved token as it becomes available —
      **3 of 4 joined for real, 2026-07-02**, via the new guarded
      `swarm-join.yml` playbook (ADR 0017), one worker at a time. The fourth
      awaits reachable hardware; this task stays scoped to "as it becomes
      available," which is honestly true for 3 of 4 today [`infra/swarm`]
- [ ] Confirm `docker node ls` shows the manager plus all four workers —
      **3 of 4 confirmed** (`Ready`/`Active`, none promoted to manager); the
      full-fleet milestone stays open until the fourth Pi joins
- [x] Deploy the harmless multi-arch smoke service (`traefik/whoami`, global mode)
      and confirm placement on each worker via `docker service ps` — **done for
      real, 2026-07-02**, `make cluster-smoke-test`: 3/3 currently-joined
      workers reached `Running`, none scheduled on the manager, service
      self-removed cleanly. Found and fixed a real bug while auditing the
      previously-documented command first: `--mode global --replicas 1` is
      invalid (`--replicas` only applies to replicated mode) and had no
      placement constraint at all, so it would have scheduled onto the manager
      too — see `infra/swarm/run-worker-smoke-test.sh` [`infra/swarm`]
- [x] Remove the smoke service; drain, remove, and rejoin one worker as a recovery
      drill, confirming it rejoins cleanly — **done for real, 2026-07-02**,
      `infra/swarm/run-worker-recovery-drill.sh` against `worker-01`: drained,
      waited for tasks to clear (0 remained), left the
      Swarm on its own side, removed from the manager's record, then rejoined
      cleanly via `swarm-join.yml` — confirmed via a genuinely new Swarm node
      ID post-rejoin, not a stale record. Found and fixed a real Docker Swarm
      behavior along the way: `docker node rm` refuses a node that's still
      `Ready`/connected even after draining — the node has to actually run
      `docker swarm leave` itself first, and the manager takes a few seconds
      (heartbeat timeout) to mark it `down` before removal succeeds; naively
      removing without this (or forcing it) would have left the worker's own
      daemon still believing it was joined while the manager forgot it
      [`infra/swarm`]
- [x] Bring up `docker-compose.coordination.yml` (Postgres 17 + Redis 7-alpine) —
      done ahead of Milestone 1/NVMe, using recovered eMMC headroom, via
      `infra/swarm/deploy-coordination.sh`; see
      [ADR 0010](decisions/0010-coordination-stack-ahead-of-nvme.md). Both
      services are loopback-bound (confirmed via `ss -tln`) and pinned to the
      manager simply by running as a plain `docker compose` container here, not
      a Swarm service — there is no Swarm placement constraint to confirm, since
      this was never designed as a Swarm stack [`infra/swarm`]
- [x] Back up manager state (Swarm CA/raft) and locally test its recovery
      procedure — done 2026-07-02: `scripts/backup-swarm-manager-state.sh`
      (stops Docker briefly, tars `/var/lib/docker/swarm`, restarts Docker,
      automatically re-deploys the coordination stack and Portainer — see
      [ADR 0016](decisions/0016-state-backup-and-recovery.md)) ran for real
      on the coordination host: archive produced
      (`local/backups/swarm-manager/20260702T164441Z/swarm-state.tar.gz`,
      confirmed via `tar -tzf` to contain `raft/`, `certificates/`
      (including the real CA cert/key), `worker/`, `docker-state.json`,
      `state.json`), Docker came back up cleanly, the coordination stack
      and Portainer re-deployed automatically, and `docker node ls`
      confirmed the manager stayed healthy (`Leader`, `Active`)
      post-backup. A live restore test was deliberately **not** run —
      operator's explicit choice, since this is the only Swarm manager and
      ADR 0016 already scoped backup + integrity verification as
      sufficient for routine validation; `scripts/restore-swarm-manager-state.sh`
      exists and is documented but remains untested against real state

### Fleet bring-up (this session, folded into this milestone)
**Three of the four planned Pi workers joined the Swarm for real, 2026-07-02.**
`worker-01`/`worker-02`/`worker-03` (the fourth, formerly "Pi master," stayed
unreachable and was deliberately excluded rather than blocking the other
three) were wired over Ethernet on the same subnet as the coordinator and
brought in through a fully guided, phase-gated session run from a phone
(Termius): passwordless SSH bootstrap with a dedicated keypair
(`infra/ansible/bootstrap-worker-ssh.sh`), Ansible connectivity, real
health/benchmark runs, Docker onboarding (ADR 0015, run for the first time
against physical hardware), a new guarded Swarm-join playbook
([ADR 0017](decisions/0017-guarded-swarm-worker-join-automation.md), amends
ADR 0015's manual-join clause without reversing its safety intent), a
worker-only smoke test, and a full one-worker recovery drill — see the
Tasks below for each real result. Real cross-node-type benchmark data now
exists: the Pi 3Bs measured ~4,630–4,650 releases/sec on the CPU/memory
probe (n=3, within ~0.6% of each other) versus the coordination host's
~14,600 — see `docs/HARDWARE.md`'s "Measured capability" table. Two real
bugs were found and fixed in newly-written tooling along the way: the
previously-documented smoke-test command (`--mode global --replicas 1`)
was actually invalid and lacked a placement constraint, and `docker node
rm` was found to refuse a still-`Ready` node even after draining — the
worker has to run `docker swarm leave` itself first, with the manager
taking a few seconds to notice, before removal succeeds. **This is
honestly partial progress, not full-fleet completion** — see the Tasks
above, most now checked with an explicit "3 of 4" caveat rather than
claiming the full milestone.

### Worker hardening, tooling, and monitoring (this session, folded into this milestone)
Real, live-verified follow-up the same night, ahead of wiring up the fourth Pi:

- [x] **Resilience: confirmed for real, not inferred from config.** Docker
      was already `enabled`/`active` on all 3 workers (the `get.docker.com`
      installer's default) and NetworkManager's `eth0` already had
      `autoconnect: yes` — but nobody had actually power-cycled a joined
      worker yet. `infra/ansible/reboot-and-verify-worker.sh` rebooted
      `worker-01` and confirmed it returned to `Ready`/`Active`
      with the **identical** Swarm node ID (`665zdixx9qpnlgsk7n0nq1fva`)
      automatically — zero manual `docker swarm join` needed after a reboot
      [`infra/ansible`]
- [x] **Hardware watchdog armed on all 3 workers**
      (`infra/ansible/playbooks/harden-workers.yml`,
      `RuntimeWatchdogSec=30`/`RebootWatchdogSec=10min`) — `/dev/watchdog`
      existed but was unarmed on all 3, confirmed live before fixing. This
      is the Pi-specific hardening pass ADR 0014's own Revisit trigger named
      as a future step; narrower than the coordinator's `harden.yml` since
      journald was already persistent and no swap exists on these Pis
      (confirmed live, not re-applied as a no-op) [`infra/ansible`]
- [x] **Docker log rotation configured on all 3 workers**
      (`max-size: 10m`, `max-file: 3`) — no `/etc/docker/daemon.json` existed
      before, confirmed live; real risk on SD-card-backed storage with
      finite write endurance [`infra/ansible`]
- [x] **Speculative-but-grounded baseline tooling installed on all 3 workers**
      (`infra/ansible/playbooks/equip-workers.yml`): `jq`/`redis-tools` (via
      the previously-inert `baseline_packages` var, now actually consumed
      for the first time), `uv` 0.11.26, DuckDB CLI v1.5.4, and a `uv`-managed
      venv (`redis` 8.0.1, `rq` 2.10.0, `duckdb` 1.5.4 — no compile step,
      prebuilt aarch64 wheels) at
      `~/.local/share/networked-players/worker-venv`, matching
      `docs/ARCHITECTURE.md`'s stated "Redis and RQ are the default
      direction." Deliberately excludes `lxml`/`pyarrow`/`packages/catalog`
      — those remain coordination-host/workstation-only per `AGENTS.md`
      [`infra/ansible`]
- [x] **Portainer Agent deployed and confirmed working** — real result,
      not just placement. First attempt used a guessed image tag
      (`portainer/agent:2.31.5`) that doesn't exist ("No such image" on all
      4 nodes); fixed to the verified, published `2.39.4` (matching the
      already-deployed `portainer-ce:2.39.4`). After the fix, all 4 nodes
      run the agent (`docker service ps`: `Running` on the manager and all
      3 workers). The operator added a second Portainer environment
      (Agent mode, `tasks.agent:9001`) and confirmed it live: dashboard
      shows "Nodes in the cluster: 4" and container/image/network counts
      roughly double the local-socket-only view, proving real cluster-wide
      aggregation, not just node listing. Extends
      [ADR 0008](decisions/0008-portainer-swarm-visibility.md) (amended
      2026-07-03) rather than a new tool/ADR; Prometheus/Grafana/cAdvisor
      remain deliberately deferred [`infra/swarm`]

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
- [x] Write `infra/ansible/playbooks/onboard.yml` (installs Docker and prints the
      real `docker swarm join` command for the `workers` group; verifies Docker on
      `optional_build_nodes` without installing or joining anything) and
      [ADR 0015](decisions/0015-fleet-onboarding.md) — the tooling exists and
      passed `--syntax-check`, but has not been run against any physical Pi or the
      second ZimaBoard yet [`infra/ansible`]. **Update, 2026-07-04:** since run for
      real against all three reachable Pi workers (ADR 0015/0017) and the second
      ZimaBoard, which joined as the x86 worker (ADR 0022/0023)

## Milestone 3: Real ingestion dry run (ROADMAP 3)

**Done as of 2026-07-02 00:02:49 EDT** — every task below is complete, including a
genuinely finished full unbounded parse with a clean full-dataset `validate` pass.
Milestone 5 is unblocked.

### Goal
Prove the existing, tested catalog pipeline against a real Discogs snapshot on real
hardware — the prerequisite for every later graph milestone.

### Depends on
Milestone 1's NVMe relocation — satisfied (see [ADR 0013](decisions/0013-nvme-storage-layout.md)
and "Where things stand today" above; 869.2 GB free, confirmed via the Ansible
health playbook).

### Tasks
- [x] Run `make ingest-check` (wraps `scripts/check-ingest-feasibility.sh`) and
      confirm it reports enough free space before attempting anything real —
      confirmed 2026-07-01 against `SNAPSHOT=20260601` (11 GB free on the eMMC,
      well above the script's own 500MB/700MB floors; this check runs before the
      manifest, so it isn't gated on the 250 GB NVMe floor). Along the way, found
      and fixed two real bugs in the script itself: a `set -euo pipefail` pipeline
      that silently killed the script on a 403 response instead of reporting it,
      and a plain `uv sync` (missing `--extra dev`) that uninstalled `ruff`/`mypy`/
      `pytest` [`scripts/`]
- [x] Obtain a real monthly snapshot manifest and confirm the object URL resolves —
      the direct-S3 URL scheme returned a bucket-level `AccessDenied` (confirmed via
      `curl` against both the object and the bucket root — not snapshot- or
      network-specific). Root cause: Discogs moved public dump hosting behind a
      Cloudflare proxy at `data.discogs.com` with a query-string download endpoint,
      not the old direct path. Fixed in `manifest.py`'s `object_url()`; verified the
      real `20260601` releases object exists and is fetchable (11,099,074,063 bytes,
      matching `DATA_SIZING.md`'s estimate) via a headers-only GET, without
      downloading it. `check-ingest-feasibility.sh`'s HEAD-based size probe also
      needed fixing — the new host never returns `Content-Length` on `HEAD`
      [`packages/catalog`, `scripts/`]
- [x] Run a bounded `MAX_RELEASES` slice end to end (`make ingest`) and record
      observed elapsed time, peak memory, and input/output bytes per
      `docs/OPERATOR_SETUP.md`'s "Measure each run" — confirmed 2026-07-01 on the
      coordination host: 10,000 releases / 59,009 tracks / 91,202 credits parsed
      from the real 11,099,074,063-byte June 2026 `.xml.gz`, 2.3 MB Parquet output.
      Elapsed time and peak memory were **not** captured this run — a real gap, not
      a claimed figure; see `docs/DATA_SIZING.md`'s "First real measurement"
      [`packages/catalog`, `docs/DATA_SIZING.md`]
- [x] Run `validate` against the resulting dataset and confirm DuckDB invariants
      hold on real (not synthetic) data — confirmed: 0 invalid linked-artist IDs, 0
      missing credit scope, 0 orphan credits, 0 orphan tracks [`packages/catalog`]
- [x] Decide, from the measured slice, whether a full unbounded parse is
      coordination-host-feasible or workstation-only — **resolved: yes, confirmed
      by a genuinely completed full run, not just a projection.** A partial
      full-scale run earlier the same day (650,000 real releases, stopped
      deliberately, not failed) measured ~428.5 releases/sec, ~167.6 MB peak RSS
      (confirmed the streaming design stays memory-bounded at 65x the smoke-test
      scale), single-core utilization (3 of 4 host cores idle), and projected
      ~12.4 hours for a full parse at that rate. After the same-day
      `_text()`/`findtext()` hot-path fix (~1.9x) and write-overlap thread
      (~4.2%), a genuine full, unbounded parse of the June 2026 snapshot was
      launched at 17:59:48 EDT via the hardened supervised pipeline
      (`SNAPSHOT=20260601 OVERWRITE=1 ./scripts/run-ingest-supervised.sh`,
      [ADR 0014](decisions/0014-coordination-host-hardening.md)) and **ran to
      completion at 00:02:49 EDT the next day (6h 3m elapsed)**: 19,192,301
      releases / 178,224,810 tracks / 220,015,758 credits parsed, ~881
      releases/sec average (roughly double the pre-fix rate), 6.6 GB Parquet
      output, memory flat around 5.8 GB available throughout (no leak across 19M+
      releases), 850 GB disk free at completion. The pipeline's own step 4/4 ran
      `validate` automatically against the full dataset and reported **0 invalid
      linked-artist IDs, 0 missing credit scope, 0 orphan credits, 0 orphan
      tracks** — the coordination host is confirmed feasible for this job
      unattended, and this closes the milestone's last open task with a real,
      completed result rather than a projection. See `docs/DATA_SIZING.md`'s
      "Partial full-scale run," "Real profiling," "'Light' parallelism," and
      "Full unbounded run: complete" sections [`packages/catalog`,
      `docs/DATA_SIZING.md`]

### Host reliability and performance work (this session, folded into this milestone)
This work exists because the operator asked, ahead of the full run above, to
harden the coordination host for long-term unattended background jobs and to
look for safe parallelism — see [ADR 0014](decisions/0014-coordination-host-hardening.md).
- [x] Persistent journald storage, a hardware watchdog
      (`RuntimeWatchdogSec`/`RebootWatchdogSec`), Docker log rotation
      (`max-size`/`max-file`), and `vm.swappiness` tuning via
      `infra/ansible/playbooks/harden.yml` — found and fixed three real bugs along
      the way: play-level `become: true` hanging the implicit facts-gathering
      task, `live-restore: true` being flatly incompatible with Docker Swarm mode
      (took `dockerd` down until reverted), and a failed handler silently blocking
      a later-notified handler in the same play [`infra/ansible`]
- [x] A supervised-job pattern (`scripts/run-ingest-supervised.sh`,
      `scripts/monitor-heavy-job.sh`) running ingestion as a resource-bounded
      (`Nice=10`, `IOSchedulingClass=best-effort`, `MemoryMax=4G`) `systemd-run`
      transient unit with an auto-launched progress monitor, independent of the
      operator's terminal session [`scripts/`]
- [x] Found and fixed two real bugs surfaced by dogfooding the above: a redundant
      re-download of an already-verified 11 GB file (`run-ingest.sh` had no
      skip-if-present check), and a `FileExistsError` on re-run with no way to
      opt into replacing an existing dataset (added an explicit `OVERWRITE` env
      var rather than failing silently) [`scripts/`]
- [x] Real `cProfile` profiling of the parser — contradicting the initial
      "decompression or Parquet writing" hypothesis — found the actual bottleneck
      was `releases.py` calling `findtext()` once per field (~79 calls per
      release), each a fresh linear scan of the element's children. Fixing it
      (build each element's child-text map once) cut measured parse time
      **~1.9x** [`packages/catalog`]
- [x] Added a bounded single-background-thread write/parse overlap in
      `parquet.py` (`ThreadPoolExecutor(max_workers=1)`, one write in flight at a
      time) — measured **~4.2%** further real improvement; a chunk-size tuning
      experiment (`--chunk-releases 50000` vs. the 5000 default) was also tried
      and showed no measurable difference, reported as a real negative result
      rather than assumed to help [`packages/catalog`]
- [x] An end-to-end ntfy.sh push-notification pipeline
      (`scripts/lib/notify.sh`, enhancements to the two scripts above,
      `scripts/install-run-and-ntfy.sh`, and a Claude Code `PreToolUse`/
      `PostToolUse` hook pair for long ad hoc builds) so the operator gets a push
      notification on job start/finish instead of needing to poll — avoids the
      ambient token cost of continuous status-checking. Verified end to end with
      real notifications received, including a real bug fix along the way (a
      stale, broken `ntfy` block earlier in `~/.bashrc` was shadowing the correct
      one) [`scripts/`, `.claude/hooks/`]

## Milestone 4: Private seed import (ROADMAP 3)

### Goal
Build the missing mechanism that turns a local Discogs collection export into a
local, never-published release-ID seed the pipeline can consume.

**Done.** This milestone did not actually require Milestone 3's real dataset —
only *using* the seed downstream (Milestone 5) does, since the import mechanism
itself never checks a release ID against any dataset. See
[ADR 0011](decisions/0011-private-seed-contract.md).

### Depends on
Nothing outstanding. (Milestone 5, which consumes this milestone's output, still
depends on Milestone 3.)

### Tasks
- [x] Define the smallest seed input contract (`SeedManifest`: `seed_version`,
      `source`, `imported_at`, a deduplicated/sorted `release_ids: list[int]`)
      and store the real seed under `data/private/`, not `local/` as originally
      sketched — matches `docs/DATA_AND_RIGHTS.md`'s "Private seed" data-class
      naming and inherits an existing agent-level `Read` deny in
      `.claude/settings.json` as defense in depth [`packages/catalog`,
      `data/contracts/discogs-seed-v1.md`]
- [x] Implement `import-seed` (`discogs/seed.py`, wired into `cli.py`) — reads
      exactly one column (`release_id`) from a source CSV and has no code path
      that reads any other column, so account-linked fields are structurally
      excluded, not filtered after the fact [`packages/catalog`]
- [x] Add a synthetic seed fixture at `data/samples/discogs-collection-export.csv`
      (3 fictional releases; IDs 101/102 deliberately match the existing
      `tests/fixtures/releases.xml` fixture) [`data/samples`]
- [x] Add tests: valid seed, malformed seed (missing column, non-integer ID),
      empty seed, duplicate IDs, seed IDs absent from any dataset, manifest
      round-trip, CLI integration, and a dedicated test asserting the output
      contains no trace of any non-`release_id` column value
      [`packages/catalog/tests/test_seed.py`]
- [x] `data/private/**` already covered the new real-file paths; no `.gitignore`
      change was needed — confirmed via `git check-ignore -v`

### ADR
[ADR 0011](decisions/0011-private-seed-contract.md) — private seed contract:
release-IDs-only JSON, stored under `data/private/`.

### Real import
The operator's real Discogs collection export (standard discogs.com "Export
Collection" CSV) was imported locally this session, producing a real
`data/private/discogs-seed.json`. Per
`docs/PUBLIC_PRIVATE_BOUNDARY.md`'s "confirm no personal collection membership
can be reconstructed," neither the release-ID count nor any release ID is
recorded here or in any commit message.

## Milestone 5: One-hop catalog expansion (ROADMAP 3)

### Goal
Turn the seed's release IDs plus the real dataset into the frontier-and-filter
one-hop expansion `docs/DISCOGS_INGESTION.md` already describes, producing the
smallest real graph-ready corpus.

### Depends on
Milestone 3 — **satisfied as of 2026-07-02** (Milestone 4 was already done — the
real seed already exists locally). The full unbounded dataset (19,192,301
releases, validated clean) now exists at `local/processed/discogs/snapshot=20260601/`,
so this milestone can start.

### Tasks
- [x] Extract the seed releases' linked credited-artist IDs into an artist-ID
      frontier — `expand-one-hop` pass 1 (`onehop.py`), keyed on
      `playable_identity` so non-linked names never join the frontier
      [`packages/catalog`]
- [x] Scan the release table to retain releases containing a frontier artist —
      pass 2, a streaming DuckDB semi-join over the credits table with an
      explicit memory limit and spill directory [`packages/catalog`]
- [x] Preserve every retained release and credit row needed to prove each edge —
      no shortcut that drops evidence: ALL credit rows (including non-linked
      evidence rows) and all track rows of every retained release survive; a
      pre-rename self-check proves every output release has playable frontier
      evidence [`packages/catalog`]
- [x] Write the expanded slice as its own versioned, immutable dataset (do not
      mutate the snapshot in place) — staging dir + atomic rename to
      `local/processed/discogs-onehop/snapshot=<X>/`, five tables, manifest with
      per-file sha256 and an `expansion` provenance block; contract in
      `data/contracts/discogs-onehop-v1.md` [`packages/catalog`]
- [x] Add a test asserting the expansion is deterministic and bounded given a
      fixed seed and snapshot — `test_onehop.py`: byte-identical parquet across
      two runs, `--max-retained-releases` guard aborts before writing
      [`packages/catalog`]

All five tasks landed as code with synthetic-fixture tests. The real-data run
against `snapshot=20260601` and the real private seed is an operator step (see
`Makefile`'s `expand-onehop` target); its observed sizing gets recorded in
`docs/DATA_SIZING.md` when it happens.

**Update, 2026-07-05: the real run happened, and it found a real problem.** The
first attempt aborted on its own `--max-retained-releases` guard: one hop from
the real seed would have retained ~21% of the entire catalog. Investigation
(`docs/discogs-data/one-hop-hub-artists.md`) found this was dominated by a
handful of extremely prolific credited identities — two Discogs placeholders
("Various Artists," "Trad.") and a long tail of real, legitimately prolific
songwriters and mastering engineers, mostly via non-performer roles
(Written-By, Mastered By, Producer, etc.). Two narrow, documented exclusions
were added to `expand_one_hop`'s frontier/retention logic — placeholder
identities ([ADR 0026](decisions/0026-exclude-placeholder-artists-from-one-hop-frontier.md))
and pure non-performer role credits ([ADR 0027](decisions/0027-exclude-non-performer-roles-from-one-hop-frontier.md))
— after which the real run succeeded: 1,410,106 retained releases (7.3% of
the catalog), 868 MB total, `validate` clean. See `docs/DATA_SIZING.md` for
the full observed numbers.

**Former caveat, now resolved:** this milestone's tasks originally worried a
bounded slice from Milestone 3 might prove insufficient to build the
release→artist index this expansion needs, and that the full sequential parse
might be required first. That's moot now — Milestone 3's full unbounded parse
already completed (see above), so the frontier can be built directly from the
real, complete dataset rather than a bounded slice.

## Milestone 6: Minimal graph-core (ROADMAP 4, 5)

### Goal
Replace the `graph-core` placeholder with the smallest correctness-first
implementation capable of one-hop traversal and evidence-preserving path
reconstruction.

### Depends on
Milestone 5.

### Tasks
- [x] Choose and implement a small readable fixture representation as the
      correctness oracle — a DuckDB-backed lazy `CreditGraph` (query-per-hop BFS
      over views, not a materialized adjacency or NetworkX; the one-hop corpus can
      hold hundreds of thousands of credit rows and the coordination host's
      working budget is ~4GB). Materialization stays the recorded revisit path if
      a measured need appears. [`packages/graph-core/src/networked_players_graph_core/graph.py`]
- [x] Load the artist–release bipartite graph from the one-hop Parquet output,
      preserving release/credit evidence on each edge [`packages/graph-core`]
- [x] Implement path lookup between two artist nodes that returns the underlying
      release/credit evidence for every hop, not just artist names
      [`packages/graph-core`]
- [x] Add tests against small synthetic fixtures (a direct one-hop path, a
      non-linked contributor correctly excluded from playable nodes, and a
      missing/absent path) — `packages/graph-core/tests/` (16 tests in
      `test_graph.py`, using real Parquet fixtures written via the catalog
      package's own schemas, not `data/samples/`)
- [ ] Manually verify at least one real evidence path from the actual one-hop
      expansion end to end (not just against synthetic fixtures) — pending live
      gate F (build a real challenge.v2 artifact from the real one-hop dataset)

### ADR
Recorded in-code (module docstring of `graph.py`) rather than a standalone ADR:
the lazy/query-per-hop design and its revisit trigger (materialize only with a
measured need). No separate ADR file was judged necessary for this internal
implementation choice.

## Milestone 7: Static artifact + graph-snapshot contract (ROADMAP 4)

### Goal
Define the versioned contracts a real challenge artifact needs before generating
one, so this isn't improvised inside `apps/web`.

### Depends on
Milestone 6.

### Tasks
- [x] Define and document a graph-snapshot contract (version, source dataset
      snapshot, generation method, evidence fields retained):
      `data/contracts/graph-snapshot-v1.md` [`data/contracts/`], with
      `export_graph_snapshot`/`export-graph-snapshot` (`packages/graph-core`)
      producing `artists`/`edges` tables; 7 tests, all synthetic. Real-data
      export against a real one-hop dataset not yet run.
- [x] Define and document the static-challenge artifact contract — evolved to
      **album-centered** (v2, not the artist-path-centered de-facto v1) per
      product direction: `data/contracts/challenge-v2.md` [`data/contracts/`]
- [x] Confirm the contract records required provenance per
      `docs/DATA_AND_RIGHTS.md` (source, snapshot date, schema/parser versions,
      omitted fields) — see the Provenance section of `challenge-v2.md`

## Milestone 8: Generate and swap in the real challenge (ROADMAP 5)

> **Note:** `apps/web`'s `/demo/` page already runs on real, curated Discogs data as
> of [ADR 0012](decisions/0012-real-discogs-api-demo-challenge.md) — an API-sourced
> detour taken ahead of this milestone. The album-centered web experience (landing
> page + `/play/<album>/`, challenge.v2.json) has since landed as real, working code
> — this milestone's remaining task is generating *real* data for it, not building
> the experience itself. The original framing ("swap `challenge.v1.json`'s content
> in place") is superseded: v2 is a separate artifact and route structure, not an
> in-place edit of v1. `/demo/` remains, relabeled "Legacy demo" in the nav, pending
> an explicit decision to retire it.

### Goal
Produce one real, privacy-safe, evidence-backed album-centered challenge from the
actual one-hop graph, and swap it in for the current synthetic placeholder at
`apps/web/public/data/challenge.v2.json` — the functional core of the MVP.

### Depends on
Milestones 6 and 7.

### Tasks
- [x] Build the artifact generator itself: `build-challenge-from-dump` CLI
      (`networked_players_graph_core.challenge.build_challenge_v2` +
      `validate_challenge`, wired into `networked-players-catalog`), plus the
      committed editorial album list `data/albums/top-albums-v1.json` and the
      medium-term proxy-ranking mechanism
      (`networked_players_graph_core.analysis.rank_album_candidates`,
      `rank-album-candidates` CLI). Includes a committed leak/contract test
      suite (`test_challenge_leaks.py`, `validate_challenge`'s scan).
- [x] Build the album-centered web experience against a synthetic-but-valid
      placeholder artifact: landing-page album grid, `/play/<album>/` pages with
      find-the-connection/reveal-the-path modes, `AlbumCard`/`EvidenceCard`
      [`apps/web`]. **Running the generator against the real one-hop dataset and
      swapping in the result is the still-open part of Milestone 8** (live gate F).
- [ ] Generate one real challenge artifact from the manually verified path
      (Milestone 6) using the contracts from Milestone 7 [`packages/graph-core`,
      `data/`]
- [ ] Confirm the generated artifact contains no collection-membership signal
      beyond derived public catalog facts, per
      `docs/PUBLIC_PRIVATE_BOUNDARY.md`'s pre-publish checklist
- [ ] Replace `apps/web/public/data/challenge.v2.json`'s synthetic placeholder with
      the real generated artifact, keeping the schema unchanged [`apps/web`]
- [ ] Confirm the landing page and `/play/<album>/` pages render correctly against
      the real artifact with no code changes required [`apps/web`]
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
      [`packages/catalog`, `data/contracts/`] — real scope evidence now
      exists: a 2026-07-02 full-dataset profiling pass found 3,345,564
      distinct `role_text` values across 220,015,758 real credit rows (max
      length 2,655 chars), confirming this is genuinely free text, not a
      small enum, and any taxonomy design needs to handle a long tail, not
      just the common ~15 role strings. See
      `docs/discogs-data/raw-dump-schema.md`'s "Real full-dataset profiling"
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

- **Milestone 3 → 5 dependency bounce-back: resolved, did not occur.**
  `docs/DISCOGS_INGESTION.md` had noted the first full sequential parse might be
  needed to build a reusable release-to-artist index, even though Milestone 3
  only originally asked for a bounded slice. That question is now moot: a full
  unbounded parse ran to completion 2026-07-01 17:59:48 EDT → 2026-07-02
  00:02:49 EDT (19,192,301 releases, validated clean — see Milestone 3 and
  `docs/DATA_SIZING.md`'s "Full unbounded run: complete"), so Milestone 5 can
  build its frontier from the real, complete dataset directly. No redo needed.
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
