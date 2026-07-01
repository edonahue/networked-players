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

On the ZimaBoard 832 coordination host, `local/` is a symlink to
`/mnt/data/networked-players/local/` on a dedicated 1TB NVMe mounted at `/mnt/data` —
see [ADR 0013](decisions/0013-nvme-storage-layout.md) for the mount layout, why it's
manual (not CasaOS's Storage app), and the coordination stack's Postgres/Redis volume
migration. `ls -la local` on this host will show a symlink, not a plain directory; every
script and CLI path reference above still works unchanged, since they're all relative
paths that resolve through the symlink transparently.

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

## Which host runs what

- **Workstation / coordination host:** manifest, download, full parse, validation, canonical
  artifact retention.
- **Raspberry Pi 3B workers:** only bounded, immutable, checksummed partitions — never the
  full raw dump. See [HARDWARE.md](HARDWARE.md) and the catalog package's resource posture.
