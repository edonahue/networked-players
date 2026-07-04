# Operator setup

How to run a Discogs ingestion slice on a real machine. This is operator work for the
optional **workstation** or the **coordination host** — never a Raspberry Pi worker (a full
raw release dump exceeds the Pi 3B's bounds). The pipeline itself is documented in the
[catalog package](../packages/catalog/README.md); this runbook covers the surrounding
storage layout, sizing, and run/cleanup workflow.

## Prerequisites

See [README → Develop](../README.md#develop): `uv`, Python 3.12+, and the `libxml2`/
`libxslt` dev headers. Then `make setup`.

## Storage layout

All large and machine-specific data lives under the git-ignored `local/` directory:

```text
local/
  manifests/   discogs-<snapshot>.json     versioned dump manifests (small, JSON)
  raw/discogs/<snapshot>/*.xml.gz           downloaded compressed dumps (large)
  processed/discogs/snapshot=<snapshot>/    normalized Parquet + dataset manifest.json
```

`local/**` is already ignored by `.gitignore`, as are `*.xml.gz`, `*.parquet`, and
`*.duckdb`. Nothing here is committed. Create the directories with `scripts/run-ingest.sh`
(it makes them) or by hand.

### Storage layout on this host

On the ZimaBoard 832 coordination host, `local/` is an `/etc/fstab` bind mount onto
`/mnt/data/networked-players/local/` on a dedicated 1TB NVMe mounted at `/mnt/data` —
see [ADR 0013](decisions/0013-nvme-storage-layout.md) for the mount layout, why it's
manual (not CasaOS's Storage app), why a bind mount rather than a symlink (a `git
rebase` was found to silently delete an untracked symlink sitting where a
previously-tracked file used to live), and the coordination stack's Postgres/Redis
volume migration. `ls -la local` on this host shows a normal directory; every script
and CLI path reference above works unchanged, since a bind mount is transparent to
every tool, including git.

## Free space and sizing

See [data sizing](DATA_SIZING.md) for the full budget. In short: one compressed dump set is
~12–15 GB, the project Parquet is ~10–25 GB, and DuckDB spill / staging can temporarily add
25–75 GB. **Do not start a full ingest with less than ~250 GB free.** Steady state is
roughly 100–250 GB. Never retain expanded XML — the parser streams directly from gzip.

Check free space before a full run:

```bash
df -h local
```

## End-to-end run

`make ingest` runs the wrapper below; or run `scripts/run-ingest.sh` directly. The wrapper
is a thin, commented sequence over the four CLI commands — read it before a first run.

Start with a bounded slice (`MAX_RELEASES`) to validate the machine before a full pass:

```bash
# A 10k-release smoke slice for May 2026:
SNAPSHOT=20260501 MAX_RELEASES=10000 make ingest

# A full pass (omit MAX_RELEASES):
SNAPSHOT=20260501 make ingest
```

The underlying steps (run on a workstation or the coordination host) are:

```bash
uv run networked-players-catalog manifest  --snapshot 20260501 --output local/manifests/discogs-20260501.json
uv run networked-players-catalog download   --manifest local/manifests/discogs-20260501.json --kind releases --raw-dir local/raw/discogs
uv run networked-players-catalog parse-releases \
  --input local/raw/discogs/20260501/discogs_20260501_releases.xml.gz \
  --snapshot 20260501 \
  --source-url "https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20260501_releases.xml.gz" \
  --output-root local/processed/discogs --max-releases 10000
uv run networked-players-catalog validate --dataset local/processed/discogs/snapshot=20260501
```

(`scripts/run-ingest.sh` reads the real URL back out of the generated manifest rather than
hardcoding it a second time, so `--source-url` always matches whatever was actually fetched.)

**Data access note:** Discogs serves monthly dumps from `data.discogs.com` (a
Cloudflare-fronted download proxy, not a direct S3 path) — `manifest.py`'s `object_url()`
constructs this automatically. An older direct-S3 URL scheme (`discogs-data-dumps.s3.us-west-2.amazonaws.com`)
returned a bucket-level `AccessDenied` as of 2026-07-01, confirmed not network- or
snapshot-specific; if Discogs' hosting changes again and downloads start failing, obtain
the current official URL from [Discogs' data page](https://www.discogs.com/data/) and
either edit the manifest JSON's `url`/`source_url` directly, or pass `manifest`'s
`--base-url` flag.

## Measure each run

Record actual figures (per AGENTS.md: identify observed vs projected):

```bash
du -h local/raw/discogs/20260501/*
du -h -d 3 local/processed/discogs/snapshot=20260501
find local/processed/discogs/snapshot=20260501 -name '*.parquet' -printf '%s %p\n' | sort -n
```

The download manifest records exact compressed bytes + SHA-256; the dataset `manifest.json`
records row counts and per-Parquet-file bytes/hashes.

## Retention and cleanup

Per the [1 TB NVMe policy](DATA_SIZING.md#recommended-1-tb-nvme-policy): keep the current
and previous compressed dump set and normalized dataset (for rollback), one staging area,
and ≥20% free. After a failed or interrupted run, remove stale partial files before
retrying:

```bash
# Stale resumable-download parts:
find local/raw/discogs -name '*.part' -delete
# An incomplete processed dataset (re-parse is idempotent with --overwrite):
rm -rf local/processed/discogs/snapshot=<snapshot>
```

**Before deleting an interrupted parse's staging directory**
(`local/processed/discogs/.snapshot=<snapshot>.tmp-*`), check how much real,
valid output survives first — a hard kill (power loss, OOM, `kill -9`,
Ctrl-C) skips `write_release_dataset()`'s own cleanup (which only runs on a
catchable Python exception), so the staging directory can survive with
hours of real, good output in it:

```bash
SNAPSHOT=<snapshot> ./scripts/check-ingest-recovery.sh
```

Reports valid vs. corrupt part counts (a torn write can only ever be the
last part or two — see the script's own docstring) as JSON. There's no
automated resume yet — this is a status check, not a `--resume` flag — but
it tells you exactly what you'd be discarding before you `rm -rf` it.

## Lessons from the first real bring-up (2026-07-01)

Bringing the NVMe online and running the pipeline against real data for the first
time surfaced several real, reproducible issues that synthetic tests couldn't have
caught. Recorded here as a single scannable reference; each links to the commit or
ADR with full detail, so this section stays a summary, not the only copy.

- **`git rebase`/`checkout` can silently delete an untracked symlink** sitting where
  a previously-tracked file used to live, with `git status` staying clean throughout
  (an ignored path's absence isn't a "change"). Hit this for real when `local/` was
  briefly a symlink; fixed by switching to a bind mount instead — see
  [ADR 0013](decisions/0013-nvme-storage-layout.md).
- **Two Compose files in the same directory share a project name if neither sets one
  explicitly**, even if they're logically unrelated (`docker-compose.coordination.yml`
  vs. `docker-compose.portainer.yml` in `infra/swarm/`). `docker compose down`
  without `--remove-orphans` is safe; adding that flag to silence the resulting
  warning would stop the other stack's containers. Documented as an inline caution in
  both compose files rather than fixed, since fixing it would force a Portainer
  first-login reset.
- **CasaOS's `local-storage.service` catalogs every block device from its own
  periodic scan**, independent of how (or whether) it's mounted — manually mounting a
  drive via `/etc/fstab` doesn't hide it from the CasaOS Storage UI, it just skips
  CasaOS's own one-click format/eject controls.
- **Discogs moved public dump hosting off the direct S3 bucket path** to a
  Cloudflare-fronted `data.discogs.com` proxy with a query-string download scheme
  (`?download=<url-encoded key>`), confirmed via a generic `AccessDenied` on both the
  object and the bucket root — not network- or snapshot-specific, not something a
  retry fixes. See the "Data access note" above.
- **A shell pre-flight check can silently die instead of degrading gracefully.**
  `check-ingest-feasibility.sh` originally used `curl -sIL` (HEAD) to probe object
  size; under `set -euo pipefail`, a `grep` finding no `content-length:` line (e.g.
  the 403 above) killed the script before its own intended "treat as unsafe" fallback
  ever ran. Separately, `data.discogs.com` never returns `Content-Length` on `HEAD`
  at all (confirmed) and doesn't honor `Range` requests either — the fix is a
  headers-only `GET` (`urlopen()` without calling `.read()`), fast regardless of
  object size.
- **A helper script's own `uv sync` can silently degrade the dev environment.**
  `check-ingest-feasibility.sh` called plain `uv sync` (no `--extra dev`), which
  uninstalled `ruff`/`mypy`/`pytest` if they'd already been installed via
  `make setup`, breaking `make check` for the rest of the session with no warning.
- **A hardcoded URL/constant duplicated across scripts drifts.** The old S3 URL was
  hardcoded independently in `manifest.py`, `run-ingest.sh`, *and*
  `check-ingest-feasibility.sh`; fixing the first two still left the third pointing
  at the dead host. All three now read the URL back from the generated manifest (the
  single source of truth) instead of reconstructing it.
- **A free-space check can measure the wrong filesystem after a storage migration.**
  `check-ingest-feasibility.sh`'s pre-flight check ran `df -Pk .` from the repo root
  (the eMMC) even after `local/` moved to the NVMe — comparing an ~11GB object against
  the eMMC's ~11GB free instead of the NVMe's ~869GB free, which would have reported
  `NOT SAFE` for a completely wrong reason. Fixed by checking `local` explicitly for
  the dump-size gate, while still correctly checking the repo root for `uv sync`'s own
  eMMC-resident `.venv` headroom.

## Which host runs what

- **Workstation / coordination host:** manifest, download, full parse, validation, canonical
  artifact retention.
- **Raspberry Pi 3B workers:** only bounded, immutable, checksummed partitions — never the
  full raw dump. See [HARDWARE.md](HARDWARE.md) and the catalog package's resource posture.

## Backup and recovery

Two independent recovery concerns, with different risk profiles — see
[ADR 0016](decisions/0016-state-backup-and-recovery.md) for the full reasoning.
Both back up to `local/backups/` (already git-ignored; never committed).

### Coordination stack (Postgres/Redis)

Low-stakes: a dev-loop database with no real consumers yet. Zero-downtime,
logical backup via `pg_dump`/Redis `BGSAVE`. No root needed *if* your user is
in the `docker` group; both scripts fall back to `sudo` automatically if not
(true on this host today — expect a `[sudo] password for ...:` prompt).

```bash
make backup-coordination
# writes local/backups/coordination/<timestamp>/{postgres.sql,redis-dump.rdb,manifest.json}

make restore-coordination BACKUP_DIR=local/backups/coordination/<timestamp>
# requires the stack already up (./infra/swarm/deploy-coordination.sh)
```

Run a backup before anything that touches the stack destructively (a schema
change, a Docker daemon restart, etc.). **Real round-trip test, confirmed
2026-07-02:**

```bash
sudo docker compose -f infra/swarm/docker-compose.coordination.yml exec redis redis-cli SET test-marker hello
make backup-coordination
make restore-coordination BACKUP_DIR=local/backups/coordination/<the-new-timestamp>
sudo docker compose -f infra/swarm/docker-compose.coordination.yml exec redis redis-cli GET test-marker
# -> "hello"
```

### Swarm manager state (CA/raft)

Higher-stakes: this is the only Swarm manager. There's no logical-export
equivalent for the raft store, so the backup briefly stops the Docker daemon
— which also stops the coordination stack (see ADR 0014's `unless-stopped`
finding). The backup script re-deploys the coordination stack automatically
afterward, but expect a real, brief outage while it runs.

```bash
make backup-swarm-manager
# writes local/backups/swarm-manager/<timestamp>/swarm-state.tar.gz (chmod 600)

# Verify without restoring:
tar -tzf local/backups/swarm-manager/<timestamp>/swarm-state.tar.gz

# Only if you actually need to restore -- replaces the manager's identity:
make restore-swarm-manager BACKUP_FILE=local/backups/swarm-manager/<timestamp>/swarm-state.tar.gz
```

The restore script keeps the pre-restore state at `/var/lib/docker/swarm.bak`
rather than deleting it, but still stops Docker while it runs. Because this
is currently the only Swarm manager (no fallback to recover from a botched
restore), treat a live restore test as a deliberate decision, not a routine
check — a backup plus a `tar -tzf` integrity check is enough validation for
routine use. **Confirmed 2026-07-02:** a real backup ran cleanly (Docker
stopped, archive made, Docker restarted, coordination stack and Portainer
auto-redeployed, `docker node ls` still showed the manager healthy
afterward), and the archive's `tar -tzf` listing showed the expected
`raft/`, `certificates/`, `worker/`, `docker-state.json`, `state.json`. A
live restore was deliberately not tested, per the reasoning above.

**Both are local-only.** Neither backup copies data off this host — a total
loss of `/mnt/data` loses these too. Off-host replication isn't built yet
(see ADR 0016's Consequences).
