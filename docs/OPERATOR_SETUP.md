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

## Real one-hop expansion (Gate B)

**Host: master/coordination only.** Do not run any of this on the x86 worker or a Pi —
those only ever receive a *replicated* one-hop dataset (see "Replicating datasets to
worker caches" below), never produce one themselves.

### Preconditions

- Clean tree, latest `main` pulled.
- `make check` green — your call whether to run it first; not required to proceed.
- A completed parsed dataset exists at `local/processed/discogs/snapshot=<SNAPSHOT>`
  (from a prior full ingest — see "End-to-end run" above) and its own `validate` already
  passed.
- The private seed file exists at `data/private/discogs-seed.json` (produced by
  `import-seed`; never committed — `data/private/` is git-ignored).
- Free space checked (see "Free space and sizing" above).
- No conflicting job currently running against `local/` (no ingest, no `catalog-data`
  server, no backup/restore).

### 1. Preflight (read-only, safe to run any time)

```bash
cd ~/networked-players
git status
git pull
make check   # optional -- skip if you've already confirmed it's green
ls -d local/processed/discogs/snapshot=*      # confirm the parsed dataset exists
ls data/private/discogs-seed.json             # confirm the seed file exists
df -h local
```

Stop if the tree isn't clean, `make check` fails (if you chose to run it), the snapshot
directory or seed file is missing, or free space looks thin against `docs/DATA_SIZING.md`.

If you're resuming a cohort rehearsal that already started, `uv run networked-players-catalog
cohort-pipeline-status --source-id <source-id>` is the companion read-only command. Use
preflight before the first run; use status when you need the current checkpoint, the missing
artifacts, and the next step without mentally re-checking every path.

### 2. Run the real expansion

```bash
SNAPSHOT=20260601 make expand-onehop ARGS='--max-retained-releases 500000'
```

Substitute your real completed snapshot date. `--max-retained-releases` is a built-in
abort guard — if the expansion would retain more releases than this, it aborts and
writes nothing rather than silently producing an oversized dataset; pick a number
comfortably above what you expect, and tighten it once you've seen a real count. Add
`--overwrite` only if `local/processed/discogs-onehop/snapshot=<date>` already exists and
you mean to replace it.

Expected: a manifest-shaped JSON printed to stdout, ending in an `expansion` object with
non-zero `frontier_artist_count` and `retained_release_count`. That object also includes
`seed_release_count` and `seed_sha256` — expected fields, not a leak (see "What must
never be committed" below).

### 3. Validate it

```bash
uv run networked-players-catalog validate --dataset local/processed/discogs-onehop/snapshot=20260601
```

Expected: JSON with zero `orphan_*` / `invalid_linked_artist_ids` counts, same shape as
validating the raw parse.

### 4. Inspect size and manifest (local-only, read-only)

```bash
du -h -d 2 local/processed/discogs-onehop/snapshot=20260601
find local/processed/discogs-onehop/snapshot=20260601 -name '*.parquet' -printf '%s %p\n' | sort -n
python3 -m json.tool < local/processed/discogs-onehop/snapshot=20260601/manifest.json | head -40
```

### 5. Capture notes (local-only; never commit)

```bash
mkdir -p local/notes
{
  echo "date: $(date -Is)"
  echo "snapshot: 20260601"
  echo "wall clock: <fill in>"
} >> local/notes/gate-b-onehop-runs.md
```

### Stop conditions

- `data/private/discogs-seed.json` is missing — re-run `import-seed` first; don't
  fabricate one.
- The source `snapshot=<date>` dataset is missing, or its own `validate` previously
  failed.
- `df -h local` shows low headroom against `docs/DATA_SIZING.md`.
- `expand-one-hop` aborts on `--max-retained-releases` — this is a safety stop, not a
  bug; investigate why the retained count is so high before raising the bound.
- `validate` on the one-hop output reports any `orphan_*` or `invalid_linked_artist_ids`
  count above zero.
- The one-hop output size is wildly larger than expected relative to the source parse.
- Any command prints a real IP, hostname, or path you don't recognize — stop and check
  `--dataset`/`--output-root` before continuing.
- The host is under memory/CPU/thermal stress (`make cluster-health` or the benchmark
  tooling) — lower `--memory-limit`/`--threads`, or stop.

### Safe-to-stop checkpoints

- Before step 2 — nothing has changed yet.
- After step 2, before step 3 — the one-hop dataset exists on disk but is unvalidated;
  safe to leave indefinitely, just don't treat it as trustworthy yet.
- After step 3 validates clean — **this is Gate B, done.** Safe to stop here
  indefinitely; nothing later is time-sensitive.
- Before any replication (below) or real challenge-artifact generation — both are
  separate, later, opt-in steps.

### Expected outputs

- `local/processed/discogs-onehop/snapshot=<date>/manifest.json`
- `local/processed/discogs-onehop/snapshot=<date>/table={releases,tracks,credits,frontier_artists,seed_releases}/`
- A clean `validate` result
- Your own notes under `local/notes/` (git-ignored)

### Recovery guidance

`expand-one-hop` stages into `.snapshot=<date>.tmp-<uuid>` and only atomically renames it
into place at the very end, so an interrupted run (kill, power loss, Ctrl-C) never leaves
a partial `snapshot=<date>` directory. If interrupted: remove any lingering
`local/processed/discogs-onehop/.snapshot=<date>.tmp-*` directory and just re-run the same
command (no `--overwrite` needed, since no complete output exists yet). Use `--overwrite`
only when a complete `snapshot=<date>` directory already exists and you deliberately want
to replace it (seed changed, or you're widening `--max-retained-releases`). Safe to
delete: any lingering `.tmp-*` staging directory, or the whole `snapshot=<date>` output —
it's fully reproducible from the source parse plus the seed.

**What must never be committed:** anything under `local/` or `data/private/` (both
already git-ignored) — including the manifest's `seed_sha256` and `seed_release_count`
fields, which are expected to exist locally but must never be pasted into a commit,
issue, or shared chat log.

### Explicit non-goals for this runbook

Do not do any of the following as part of Gate B — each is a separate, later, opt-in
step already documented elsewhere:

- Replicate the resulting one-hop dataset to the x86 worker or a Pi (see "Replicating
  datasets to worker caches" immediately below).
- Run a Pi cache trial.
- Generate a real `challenge.v2.json` (`build-challenge-from-dump`).
- Retire `/demo/`.
- Deploy.

## Real cohort rehearsal (first source)

**Host: developer machine or master/coordination for steps 1-2 and 5-7 (no dataset
needed); whichever host has the relevant dataset locally for steps 3-4 — prefer the x86
worker for a real one-hop dataset (see "Replicating datasets to worker caches" below).
Never a Pi for steps 3-4.**

This walks through `docs/COHORT_SOURCE_INGESTION.md`'s pipeline against a real,
operator-saved source for the first time. See `data/contracts/album-cohort-extracted-v1.md`
/ `-resolved-v1.md` / `-connectivity-v1.md` / `playable-cohort-v1.md` for what each step
actually produces; this section is the operational sequence, not the schema reference.

### Preconditions

- A source page manually saved by the operator (however they choose) — **no command in
  this pipeline fetches anything live, ever, by design**, per
  [ADR 0028](decisions/0028-curated-cohort-source-ingestion.md).
- The saved page placed at `data/private/source-html/<source-id>.html`. There is no
  separate "source notes" file any command reads — jot down the source URL/title yourself
  however you like; they're just the values you'll pass to step 2's flags directly.
- A completed, `validate`-clean parsed dataset for resolution (step 3), and a completed,
  `validate`-clean one-hop dataset for scoring (step 4) — see "Real one-hop expansion
  (Gate B)" above if the one-hop dataset doesn't exist yet.
- `make check` green — your call whether to run it first; not required to proceed.

### 0. Automated preflight (read-only, safe to run any time)

```bash
uv run networked-players-catalog cohort-pipeline-preflight \
  --source-id <source-id> \
  --source-html data/private/source-html/<source-id>.html \
  --parsed-dataset local/processed/discogs/snapshot=<SNAPSHOT> \
  --onehop-dataset local/processed/discogs-onehop/snapshot=<SNAPSHOT> \
  --source-url "<the real URL you saved it from>" \
  --source-title "<the page's own title>"
```

This is read-only: it checks that the saved page and both dataset roots exist (a dataset
root check means the directory plus its `manifest.json`, not that the dataset's contents
are valid — `validate`/`verify-dataset` are still what confirms that), warns about any
step's output file that already exists and would be overwritten by a re-run, and prints
the exact commands for steps 2-7 below with `--source-url`/`--source-title` already
shell-quoted. It runs none of those commands itself. Exit code is `0` when every required
input is present, `1` otherwise — useful in a script, but reading the printed report is the
point. Pass `--json` for machine-readable output instead.

### 1. Manual preflight (read-only, safe to run any time)

```bash
cd ~/networked-players
ls data/private/source-html/<source-id>.html      # confirm the saved page exists
ls -d local/processed/discogs/snapshot=*          # confirm a parsed dataset exists
ls -d local/processed/discogs-onehop/snapshot=*   # confirm a one-hop dataset exists
```

Stop if the saved page or either dataset is missing. Step 0's automated check above covers
the same ground; this is here for a quick manual look without picking snapshot flags.

### 2. Import

```bash
uv run networked-players-catalog import-cohort-source \
  --input data/private/source-html/<source-id>.html \
  --output local/analysis/cohorts/<source-id>/extracted.json \
  --source-url "<the real URL you saved it from>" \
  --source-title "<the page's own title>"
```

Expected: `album-cohort-extracted-v1.json`-shaped output with a non-zero `candidate_count`.
A `low_confidence_count`/`missing_link_count` above zero isn't an error — it's real,
honest signal for review later, never silently fixed up.

### 3. Resolve (needs the parsed dataset)

```bash
uv run networked-players-catalog resolve-cohort \
  --extracted local/analysis/cohorts/<source-id>/extracted.json \
  --dataset local/processed/discogs/snapshot=<SNAPSHOT> \
  --output local/analysis/cohorts/<source-id>/resolved.json
```

Run on whichever host has `local/processed/discogs/snapshot=<SNAPSHOT>` — the
master/coordination host for its own authoritative copy, or SSH to
`<x86-worker-ssh-target>` if resolving against its replicated cache instead.

### 4. Score (needs the one-hop dataset)

Before scoring a real cohort with format-aware evidence, generate the local
classification and inspect the title-policy transition. These commands do not
publish anything and do not call the API:

```bash
uv run networked-players-catalog classify-release-formats \
  --dataset local/processed/discogs-onehop/snapshot=20260601 \
  --output local/analysis/cohorts/<source-id>/release-format-policy.json

uv run networked-players-catalog compare-release-format-policy \
  --dataset local/processed/discogs-onehop/snapshot=20260601 \
  --policy local/analysis/cohorts/<source-id>/release-format-policy.json \
  --output local/analysis/cohorts/<source-id>/format-policy-shadow.json

uv run networked-players-catalog build-release-format-scoring-index \
  --policy local/analysis/cohorts/<source-id>/release-format-policy.json \
  --output local/analysis/cohorts/<source-id>/release-format-scoring-index.json
```

Review the disagreement list before adding the compact scoring index through
`--release-format-policy`. The policy requires an explicit Album descriptor and excludes
Compilation, Sampler, Single, EP, Live, Remix, Bootleg, Soundtrack, and Box Set
evidence. Missing or ambiguous format data remains review-required.

```bash
uv run networked-players-catalog score-cohort-connectivity \
  --resolved local/analysis/cohorts/<source-id>/resolved.json \
  --dataset local/processed/discogs-onehop/snapshot=<SNAPSHOT> \
  --output-dir local/analysis/cohorts/<source-id>/ \
  --release-format-policy local/analysis/cohorts/<source-id>/release-format-policy.json \
  --memory-limit 3GB --threads 3 --pair-timeout-seconds 180
```

Prefer the capability platform for a real one-hop dataset. The selected x86 worker must
advertise the exact scorer commit, `cohort.score` workload version, memory policy, tags,
and verified dataset manifest. Build and deploy the clean commit first (see
`infra/ansible/README.md`), then submit from the coordination host:

```bash
make score-cohort-on-worker ARGS="--source-id <source-id> --snapshot-date <SNAPSHOT>"
# Optional policy pin: --worker-id <opaque-worker-id> --memory-limit 2GB --threads 3
```

The controller creates a unique local and remote run directory, hashes `resolved.json`,
requires the worker's exact dataset-manifest identity, and enqueues only to a fresh matching
advertisement. The worker checks the runtime commit and input hashes, writes to staging,
and publishes a completed result atomically. The controller fetches and verifies every
output hash before promoting `connectivity.json`, `playable-pairs.json`,
`review-report.md`, and `scoring-diagnostics.json` into the usual analysis directory.
Existing analysis outputs are preserved unless `--replace` is explicit.

The direct `score-cohort-connectivity` command remains an emergency/local development
path. Normal real scoring should not run on the coordination host.

**Settings for a real, hub-heavy cohort on a dedicated x86 worker.** Scoring is now
memory-bounded — all search state lives in DuckDB, so `--memory-limit` genuinely caps the
whole computation ([ADR 0033](decisions/0033-memory-bounded-cohort-scoring.md)). On the
dedicated worker use `--memory-limit 2GB --threads 3` and, because a real cohort's seeds are all
hubs, raise `--pair-timeout-seconds` to `180` (the 30 s default is for tests/tiny cohorts
and will skip every hub seed). Keep `--temp-dir` on the volume the dataset lives on if
that differs from the process CWD. A preflight refuses a `--memory-limit` above half of
the host's available RAM — the measured swap-death mode of the first real run. **Never raise `--memory-limit` to "make it pass"
without reading `scoring-diagnostics.json` first** (written next to `connectivity.json`):
it shows per-seed reach sizes, timings, and peak RSS, so you can see *where* memory or
time went rather than guessing.

Guardrails ([ADR 0033](decisions/0033-memory-bounded-cohort-scoring.md)): a hub seed that
still can't finish in the budget produces `status: "skipped"` pairs
(`seed_expansion_timeout`, `frontier_too_large`, or `reach_too_large`) — honest, expected
output, not a bug to work around. Because the frontier cap is now a *time* knob rather than
a memory one, raising `--max-frontier-expansion` (e.g. toward ~2000) is a safe way to
convert `frontier_too_large` skips into results if the diagnostics show headroom.

### 5. Draft a review template

```bash
uv run networked-players-catalog draft-cohort-review \
  --connectivity local/analysis/cohorts/<source-id>/connectivity.json \
  --output data/private/cohort-review/<source-id>-selection.template.json
```

Produces a private file with an always-empty `approved_pairs[]` and a `candidate_pairs[]`
listing every `status: "found"` pair (clean pairs first), ready for step 6. Never
pre-approves anything.

For a more compact, diversity-aware shortlist, optionally generate a local-only editorial
packet before manual review:

```bash
uv run networked-players-catalog draft-cohort-editorial-review \
  --resolved local/analysis/cohorts/<source-id>/resolved.json \
  --connectivity local/analysis/cohorts/<source-id>/connectivity.json \
  --output-json local/analysis/cohorts/<source-id>/editorial-review.json \
  --output-markdown local/analysis/cohorts/<source-id>/editorial-review.md
```

This ranks suggestions using transparent difficulty, credit-quality, warning, and
repetition signals, and caps endpoint repetition in the suggested shortlist. It is a
curation aid only: it does not approve pairs, replace the selection template, or publish
anything. Keep both outputs under `local/`, never in public or private committed data.

### 5a. Local curator UI (optional, private only)

After the editorial packet exists, use the small local curator to browse all ranked pairs,
view cached Discogs cover thumbnails, select/reject pairs, and leave private notes:

```bash
make curator SOURCE_ID=<source-id>
```

Dark mode is the default; the browser remembers the light/dark choice locally. The server
binds to loopback by default. For a trusted LAN device, make exposure explicit:

```bash
make curator SOURCE_ID=<source-id> ARGS="--host 0.0.0.0 --reviewed-by <your-name>"
```

It writes only `data/private/cohort-review/<source-id>-selection.json` in the same
promotion-compatible format used by step 6. It is not part of `apps/web`, Cloudflare, or
the public static build. Cover thumbnails are hotlinked from Discogs only when their saved
release metadata is present in the private API cache. To explicitly fetch missing metadata
into that cache, rerun `draft-cohort-editorial-review` with `--enrich-images`; that is a
rate-limited, token-gated coordination-host action, never a Pi or browser action.

### 6. Human review (manual — no command does this step)

Open `<source-id>-selection.template.json`, read `review-report.md` (from step 4) and
`candidate_pairs[]` alongside each other, and for every pair you're genuinely satisfied
with, move its `{album_a_id, album_b_id}` from `candidate_pairs[]` into `approved_pairs[]`.
Set `reviewed_by`/`reviewed_at`, and a `review_note` if you want one published. Save as
`data/private/cohort-review/<source-id>-selection.json` — **not** the `.template.json`
file itself; promoting the raw template produces zero promoted pairs by construction (its
`approved_pairs[]` starts empty), so there's no way to accidentally publish an unreviewed
cohort this way, but keep the two files distinct regardless.

### 7. Promote (only after step 6)

```bash
uv run networked-players-catalog promote-playable-cohort \
  --resolved local/analysis/cohorts/<source-id>/resolved.json \
  --connectivity local/analysis/cohorts/<source-id>/connectivity.json \
  --selection data/private/cohort-review/<source-id>-selection.json \
  --cohort-id <source-id> \
  --output data/albums/cohorts/<source-id>-playable-v1.json
```

Writes `data/albums/cohorts/<source-id>-playable-v1.json` — see
`data/contracts/playable-cohort-v1.md`. **This file is the only output of this whole
rehearsal meant to ever be committed, and only after you've actually reviewed it and
decided to.** Nothing in this runbook commits it for you.

### Stop conditions

- The saved source page or either dataset is missing.
- `resolve-cohort` reports a high `unresolved_count` relative to `candidate_count` — check
  `warnings[]` in `resolved.json` before proceeding; a systematically bad extraction won't
  fix itself downstream.
- `score-cohort-connectivity` reports many `"skipped"` pairs — real, honest output, but
  worth investigating (read `scoring-diagnostics.json`, then try a larger
  `--pair-timeout-seconds`/`--max-frontier-expansion`/`--max-reach-rows`) before treating
  the review report as complete.
- Any command prints a real IP, hostname, or path you don't recognize — stop and check
  `--dataset`/`--output`/`--output-dir` before continuing.

### Safe-to-stop checkpoints

- After any of steps 2-5 — each writes one plain JSON file and can be re-run idempotently;
  nothing is time-sensitive.
- Before step 7 — this is the only step whose output might ever leave `local/`/
  `data/private/`. Perfectly safe to stop indefinitely at step 6 and come back to review
  later.

### Expected outputs

- `local/analysis/cohorts/<source-id>/{extracted.json, resolved.json, connectivity.json,
  playable-pairs.json, review-report.md}` — all local-only, git-ignored, never committed.
- `data/private/cohort-review/<source-id>-selection.template.json` and
  `-selection.json` — private, git-ignored, never committed.
- `data/albums/cohorts/<source-id>-playable-v1.json` — **only after step 7, and only if
  you decide to commit it.**

### Recovery guidance

Every step's output is a single plain JSON file (or, for step 4, a small directory of
them) — if a step's output looks wrong, delete just that file/directory and re-run that
one step; there's no staged/atomic-rename machinery to worry about here the way Gate B's
expansion has, since none of these steps run long enough to need it.

### Explicit non-goals for this runbook

- Fetching the source page live, at any point, under any flag — it doesn't exist in this
  pipeline, by design, not by omission (ADR 0028).
- Automatically promoting anything — step 7 always requires a selection file with at least
  one entry a human put there themselves.
- Running the Pi ambient validation job as part of this rehearsal — see "Pi ambient
  cohort-artifact checks" below; it's a separate, optional, later re-check, not a step in
  producing or reviewing a cohort.
- Making the promoted artifact web-visible — a separate, later step, not part of
  generating and reviewing the cohort itself: adding a `status: "reviewed"` entry to
  `apps/web/public/data/cohorts/index.json` plus a matching static import in
  `apps/web/src/data/cohortArtifacts.ts` (see `docs/COHORT_SOURCE_INGESTION.md`). The
  cohort's `/cohorts/<cohort_id>/` detail page is generated automatically from the
  manifest — there is no separate routing step.

## Pi ambient cohort-artifact checks

A bounded, validation-only ambient job re-checks an already-produced
`connectivity.json` or `playable-cohort-v1.json` on the Pi fleet — no dataset, no
`CreditGraph`, no network, safe to run at any time regardless of when the artifact was
produced. This is purely a second, independent safety check (the same structural and
leak/tone checks `validate-connectivity`/`validate-playable-cohort` already run locally);
it is never required, and nothing in the rehearsal above depends on it.

```bash
# One-time: deploy the job body to the Pi fleet.
./infra/ansible/run-deploy-cohort-check-job-local.sh --limit pi_workers

# Check an already-produced artifact (paths resolve on the targeted worker, not here):
./infra/swarm/deploy-jobs-broker.sh                     # if not already running
./scripts/enqueue-cohort-check.sh --kind connectivity \
  --artifact local/analysis/cohorts/<source-id>/connectivity.json
./scripts/enqueue-cohort-check.sh --kind playable-cohort \
  --artifact data/albums/cohorts/<source-id>-playable-v1.json
```

Results are written to `local/jobs/cohort-check-<timestamp>.json` (never committed). This
mirrors the existing challenge-evidence verification job's exact deploy/enqueue pattern —
see `infra/ansible/files/cohort_artifact_check_job.py`'s own header comment for why it's a
hand-maintained mirror rather than a direct import of `networked_players_graph_core`.

## Public catalog regen

**Host: master/coordination only** — needs the full one-hop dataset, parsed masters, and
the release-format policy locally.

### Preconditions

- Clean tree, latest `main` pulled; `make check` green (optional).
- A completed one-hop dataset at `local/processed/discogs-onehop/snapshot=<date>`.
- Parsed masters at `<masters-root>/snapshot=<date>` (see "Masters parse" in
  `docs/DATA_SIZING.md`).
- A release-format policy (`release-format-scoring-index.json`) built for the same
  snapshot (see `docs/RELEASE_FORMAT_RESEARCH.md`).
- `data/albums/studio-album-master-exclusions-v1.json` (checked in) and
  `data/albums/top-albums-v1.json` (checked in, the editorial backbone).

### 1. Rank candidates (read-only against the dataset; writes local-only output)

```bash
uv run networked-players-catalog rank-album-candidates \
  --dataset local/processed/discogs-onehop/snapshot=20260601 \
  --output local/analysis/album-catalog-regen/candidates.json \
  --limit 200 \
  --release-format-policy <path-to-release-format-scoring-index.json> \
  --masters-root <masters-root>/snapshot=20260601 \
  --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json
```

### 2. Build the public catalog

```bash
uv run networked-players-catalog build-public-album-catalog \
  --onehop-root local/processed/discogs-onehop/snapshot=20260601 \
  --candidates local/analysis/album-catalog-regen/candidates.json \
  --target-count 140 \
  --output apps/web/public/data/catalog/albums.v1.json \
  --release-format-policy <path-to-release-format-scoring-index.json> \
  --masters-root <masters-root>/snapshot=20260601 \
  --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json
```

`build-public-album-catalog` requires every policy input and fails closed if one is
missing or its `snapshot_date` disagrees with the one-hop dataset's — never fall back to
the EXPLORATORY `build-album-catalog` command for the committed artifact (see its own
help text).

### 3. Validate

```bash
uv run networked-players-catalog validate-album-catalog --input apps/web/public/data/catalog/albums.v1.json
```

Expected: `{"ok": true}`. If you also maintain the inclusion audit
(`docs/data/studio-album-catalog-inclusion-audit-v1.json`), rebuild and validate it too
(`build-album-catalog-audit`/`validate-album-catalog-audit`, same policy inputs).

### Stop conditions

- Any policy input's `snapshot_date` disagrees with the one-hop dataset's.
- `validate-album-catalog` reports any failure.
- The album count drops well below the prior published catalog without a known, reviewed
  reason (a policy tightening, a new exclusion) — investigate before publishing.

### Safe-to-stop checkpoints

- After step 1 — `candidates.json` is local-only, safe to leave indefinitely.
- After step 3 validates clean — safe to stop; the new catalog is not live until it's
  committed, deployed, and every downstream artifact (Connection Guesser, Record Routes,
  album-art registry) is regenerated against its new `catalog_version` (see the
  version-relationship reference below).

### Expected outputs

- `apps/web/public/data/catalog/albums.v1.json`, with a new `catalog_version`.
- A clean `validate-album-catalog` result.

### Recovery guidance

Fully reproducible from the source dataset plus policy inputs — if something looks wrong,
re-run rather than hand-editing the output. Re-running with identical inputs is
deterministic (candidate ranking and catalog assembly are both pure functions of their
inputs).

### Explicit non-goals for this runbook

A new `catalog_version` invalidates every downstream real artifact's provenance check —
regenerating the catalog alone does not update the Connection Guesser, Record Routes, or
album-art registry. Each of those is its own separate runbook below; run them in that
order (catalog → art registry → Connection Guesser → Record Routes → daily manifest) so
each regeneration reads the catalog version the one before it just produced.

## Image-enrichment refresh

**Host: master/coordination only** — this is the one runbook here that makes real,
rate-limited outbound HTTP requests (the Discogs API), so it must never run on a
Pi/x86 worker or as an unattended fleet job.

### Preconditions

- `DISCOGS_TOKEN` set in the environment (never committed).
- The canonical catalog (`apps/web/public/data/catalog/albums.v1.json`) already reflects
  the catalog version you want art for.

### 1. Build the registry (rate-limited, cache-first, resumable)

```bash
export DISCOGS_TOKEN=<your-token>
uv run networked-players-catalog build-album-art-registry \
  --catalog apps/web/public/data/catalog/albums.v1.json \
  --output apps/web/public/data/catalog/album-art.v1.json \
  --cache-dir data/private/discogs-api-cache \
  --generated-at 2026-07-22T00:00:00+00:00
```

`--generated-at` is explicit, never the wall clock (same convention as the daily
manifest). The on-disk cache under `--cache-dir` (`data/private/`, git-ignored) makes a
re-run after an interruption resume rather than re-fetch from scratch — only successful
payloads are cached, so a transient failure is retried, not silently treated as "no
image."

### 2. Validate

```bash
uv run networked-players-catalog validate-album-art-registry \
  --registry apps/web/public/data/catalog/album-art.v1.json \
  --catalog apps/web/public/data/catalog/albums.v1.json
```

Expected: `{"ok": true, "albums_with_art": <n>}`. Compare `<n>` against the catalog's
total album count for real coverage.

### Stop conditions

- `DISCOGS_TOKEN` missing or rejected (401/403) — do not retry aggressively; check the
  token before re-running.
- Sustained 429s well beyond the built-in throttle/backoff — stop and investigate rather
  than tightening the delay downward.
- `validate-album-art-registry` reports a `catalog_version` mismatch — the catalog moved
  since this registry was built; regenerate against the current catalog, don't force it.

### Safe-to-stop checkpoints

- Any time — the on-disk cache means an interrupted run loses no completed work; just
  re-run the same command to resume.

### Expected outputs

- `apps/web/public/data/catalog/album-art.v1.json`, hotlink URLs only (no image bytes).
- The raw per-release API cache stays under `data/private/`, never committed, never
  published.

### Recovery guidance

Delete a specific cached entry under `--cache-dir` to force a refetch of just that
release; delete the whole cache directory to force a full refetch (still rate-limited).

### Explicit non-goals for this runbook

Never rehost, proxy, or commit image bytes — hotlink URLs only. Never raise the request
rate to "go faster." Never run this on a schedule without a human watching the first
completion.

## Connection Guesser regen

**Host: master/coordination only.**

### Preconditions

- A completed one-hop dataset and the current canonical catalog
  (`apps/web/public/data/catalog/albums.v1.json`), same `catalog_version` you intend to
  publish against.
- Optionally, `local/analysis/.../artist-family-exclusions-v1.json` (drops trivial
  group/frontperson pairs).

### 1. Build

```bash
uv run networked-players-catalog build-connection-rounds \
  --onehop-root local/processed/discogs-onehop/snapshot=20260601 \
  --albums apps/web/public/data/catalog/albums.v1.json \
  --artist-family-exclusions <path-to-artist-family-exclusions-v1.json> \
  --one-hop-target 300 --two-hop-target 200 \
  --memory-limit 2GB --threads 4 \
  --output-universe apps/web/public/data/game/universe.v1.json \
  --output-rounds apps/web/public/data/game/rounds.v1.json
```

Real achieved counts (not padded targets) print as diagnostics — a shortfall against the
target is expected and honest, not a bug (see `docs/DATA_SIZING.md`'s real-data launch
section for the reasoning).

### 2. Validate

```bash
uv run networked-players-catalog validate-connection-rounds \
  --universe apps/web/public/data/game/universe.v1.json \
  --rounds apps/web/public/data/game/rounds.v1.json
```

### 3. Diff against the prior publish before committing

Before replacing the committed artifacts, diff the new pair against the currently
published one (round ids, endpoints, answer sets, order) — see "Rollback" below for the
same byte-for-byte-diff discipline this project already uses for corrective regenerations.

### Stop conditions

- `validate-connection-rounds` reports any failure.
- `catalog_version` in the output provenance doesn't match the catalog you intended to
  build against.
- The round count collapses well below the prior publish without a known cause.

### Safe-to-stop checkpoints

- After step 2 validates clean — safe to stop; not live until committed and deployed.

### Expected outputs

- `apps/web/public/data/game/universe.v1.json` / `rounds.v1.json`, with new
  `pool_version`/`artifact_version`.

### Recovery guidance

Fully reproducible from the same inputs (deterministic given a fixed graph snapshot,
album list, exclusion artifact). Re-run rather than hand-editing.

### Explicit non-goals for this runbook

A new `rounds.v1.json` invalidates the daily manifest's version-agreement check — the
daily manifest must be extended (never rebuilt from scratch mid-flight) against the new
artifact separately; see "Daily-schedule extension" below. Never publish a regenerated
pool without extending or re-anchoring the daily manifest in the same change.

## Daily-schedule extension

**Host: anywhere** — pure Python, JSON-in/JSON-out, no dataset needed.

### Preconditions

- The currently published `apps/web/public/data/game/daily-manifest.v1.json` and its
  paired `rounds.v1.json` (same generation — extension fails closed on any version
  mismatch).

### 1. Check remaining runway (read-only, safe to run any time)

```bash
uv run networked-players-catalog connection-daily-manifest-status \
  --manifest apps/web/public/data/game/daily-manifest.v1.json \
  --warn-within-days 14
```

Exits 1 only if the schedule has already run out (`already_expired`); exits 0 while
merely inside the warning window, so this is safe to run as a periodic check without
treating "getting close" as a hard failure.

### 2. Extend

```bash
uv run networked-players-catalog extend-connection-daily-manifest \
  --manifest apps/web/public/data/game/daily-manifest.v1.json \
  --rounds apps/web/public/data/game/rounds.v1.json \
  --days 90 \
  --output apps/web/public/data/game/daily-manifest.v1.json \
  --generated-at 2026-07-22T00:00:00+00:00
```

Re-verifies every already-published entry's `round_fingerprint` before appending anything
— a silently changed round is caught, not propagated. Never touches an already-published
date. `--generated-at` is explicit, never the wall clock.

### 3. Validate

```bash
uv run networked-players-catalog validate-connection-daily-manifest \
  --manifest apps/web/public/data/game/daily-manifest.v1.json \
  --rounds apps/web/public/data/game/rounds.v1.json
```

### Stop conditions

- Extension raises on a version mismatch — the paired `rounds.v1.json` is a different
  generation than the manifest was built against; regenerate the Connection Guesser pool
  is not the fix here, reconcile which generation is actually live first.
- Extension raises on pool exhaustion ("no repeat policy is implemented yet") — the
  eligible one-hop pool needs to grow (regenerate the Connection Guesser pool with a
  higher `--one-hop-target`) before more dates can be scheduled.
- `validate-connection-daily-manifest` reports any failure.

### Safe-to-stop checkpoints

- Step 1 is always safe, any time.
- After step 3 validates clean — safe to stop; the extension only appended new dates,
  every prior date is byte-for-byte unchanged (confirm with a diff before committing).

### Expected outputs

- An updated `daily-manifest.v1.json`: prior entries unchanged, new entries appended,
  new `generated_at`.

### Recovery guidance

Confirm `after["schedule"][:len(before)] == before["schedule"]` before committing — the
existing extension tests assert this invariant; treat any diff outside the appended tail
as a stop condition, not something to force through.

### Explicit non-goals for this runbook

Never reassign an already-published date. Never rebuild the manifest from scratch to
"fix" it — extension is the only supported append path once the first daily is live.

## Record Routes regen

**Host: master/coordination only.**

### Preconditions

- A completed one-hop dataset, the current canonical catalog, and (for real two-hop
  bridge-release gating) the release-format policy and studio-album exclusions used to
  build the catalog itself — see `docs/DATA_SIZING.md`'s "Record Routes real-data
  generation" entry for why the format policy matters here (it gates the *hidden* middle
  record, not just the endpoints).

### 1. Build

```bash
uv run networked-players-catalog build-record-routes \
  --onehop-root local/processed/discogs-onehop/snapshot=20260601 \
  --albums apps/web/public/data/catalog/albums.v1.json \
  --artist-family-exclusions <path-to-artist-family-exclusions-v1.json> \
  --release-format-policy <path-to-release-format-scoring-index.json> \
  --studio-album-exclusions data/albums/studio-album-master-exclusions-v1.json \
  --masters-root <masters-root>/snapshot=20260601 \
  --one-hop-target 300 --two-hop-target 200 \
  --memory-limit 2GB --threads 4 \
  --output-universe apps/web/public/data/routes/universe.v1.json \
  --output-rounds apps/web/public/data/routes/rounds.v1.json
```

### 2. Validate

```bash
uv run networked-players-catalog validate-record-routes \
  --universe apps/web/public/data/routes/universe.v1.json \
  --rounds apps/web/public/data/routes/rounds.v1.json
```

### Stop conditions

- `validate-record-routes` reports any failure.
- `catalog_version` in the output provenance doesn't match the catalog you intended to
  build against.
- The run takes dramatically longer than `docs/DATA_SIZING.md`'s recorded figure for a
  comparable dataset size — stop and investigate rather than assuming it will finish;
  see that doc's "Performance: batched credit-row prefetch" note for the class of bug
  this project has already hit once here.

### Safe-to-stop checkpoints

- After step 2 validates clean — safe to stop; not live until committed and deployed.

### Expected outputs

- `apps/web/public/data/routes/universe.v1.json` / `rounds.v1.json`, with new
  `pool_version`/`artifact_version` and content-derived `route-<hash>` ids.

### Recovery guidance

Fully reproducible from the same inputs. Re-run rather than hand-editing.

### Explicit non-goals for this runbook

Record Routes has no daily schedule of its own today (see ADR 0046's revisit trigger) —
this runbook does not touch `daily-manifest.v1.json`.

## Rollback

There is no scripted revert command for any real artifact in this project — rollback is
git-history-based, following the exact precedent already used twice for real corrective
regenerations (ADR 0043's corrective-slice-4.5/4.6 addenda):

1. **Fix the root cause** first (a code bug, a bad exclusion, a stale policy input) —
   never hand-edit a published artifact to paper over a symptom.
2. **Regenerate deterministically** using the relevant runbook above.
3. **Diff the new artifact against the prior publish** on every semantic field (ids,
   endpoints, answer sets, schedule dates/order, evidence) before committing — a real
   fix should change only what the fix targets; an unexpected diff elsewhere is a stop
   condition, not something to force through.
4. **Publish via a normal PR**, reviewed and merged like any other change. If a bad
   artifact already reached `main` and deployed, `git revert -m 1 <mergeSHA>` on `main`
   (never force-push) is the actual rollback mechanism — Cloudflare's auto-deploy then
   promotes the reverted SHA.

### Explicit non-goals

Never hand-edit a committed artifact's JSON directly. Never reassign an already-published
daily-manifest date, even to fix a mistake — extend forward instead, and treat the
mistake as a known, documented gap in that date's history rather than rewriting it.

## Pi ambient artifact checks (Connection Guesser, Record Routes, daily manifest, album-art registry, catalog)

Slice 8 adds four more bounded, validation-only ambient jobs, following the exact same
pattern as "Pi ambient cohort-artifact checks" above: no dataset, no `CreditGraph`, no
network, safe to run at any time regardless of when the artifact was produced. Each is a
second, independent safety check re-running the same dependency-free validator the
`validate-*` CLI commands above already run locally — never required, and this is also
where a privacy re-scan happens for free, since every `*_failures` validator already
includes the forbidden-substring/phrase scan as part of its contract check.

```bash
# One-time per job: deploy the job body + current published artifacts to the Pi fleet.
./infra/ansible/run-deploy-connection-rounds-check-job-local.sh --limit pi_workers
./infra/ansible/run-deploy-record-routes-check-job-local.sh --limit pi_workers
./infra/ansible/run-deploy-daily-manifest-check-job-local.sh --limit pi_workers
./infra/ansible/run-deploy-album-art-check-job-local.sh --limit pi_workers
./infra/ansible/run-deploy-catalog-check-job-local.sh --limit pi_workers

# Re-check whatever was last deployed (re-run the matching deploy-*-local.sh above first
# if you want to check a freshly regenerated artifact instead of what's already there):
./infra/swarm/deploy-jobs-broker.sh                     # if not already running
./scripts/enqueue-connection-rounds-check.sh
./scripts/enqueue-record-routes-check.sh
./scripts/enqueue-daily-manifest-check.sh
./scripts/enqueue-album-art-check.sh
./scripts/enqueue-catalog-check.sh
```

Results are written to `local/jobs/<contract>-check-<timestamp>.json` (never committed).
Each deploy playbook copies its artifacts under a contract-prefixed filename
(`connection-*`, `routes-*`, `daily-manifest.v1.json`, `album-art.v1.json`/
`albums.v1.json`) specifically so more than one of these jobs can be deployed to the same
Pi's `rq_jobs_dir` at once without one silently overwriting another's input — see ADR
0043's slice-8 addendum for the real bug this closed.

## Public artifact and version-relationship reference

| Artifact | Real path | Version field(s) | Derived from | Dependency-free validator | Pi check-job | Consumers |
| --- | --- | --- | --- | --- | --- | --- |
| Public catalog | `apps/web/public/data/catalog/albums.v1.json` | `catalog_version` | One-hop dataset + masters + release-format policy + editorial list | `networked_players_contracts.catalog::public_album_catalog_failures` | `catalog_check_job.py` | Every other real artifact below |
| Album-art registry | `apps/web/public/data/catalog/album-art.v1.json` | `art_version` (+ `catalog_version` it was built against) | Discogs API, keyed by the catalog's `main_release_id`s | `networked_players_contracts.album_art::album_art_failures` | `album_art_check_job.py` | Album browser, both game modes' frontend art resolution |
| Connection Guesser | `apps/web/public/data/game/{universe,rounds}.v1.json` | `pool_version`, `artifact_version` (+ `catalog_version`) | One-hop dataset + catalog + artist-family exclusions | `networked_players_contracts.connection_rounds::connection_rounds_failures` | `connection_rounds_check_job.py` | `/play/daily/`, the daily manifest |
| Connection-daily-manifest | `apps/web/public/data/game/daily-manifest.v1.json` | `pool_version`, `artifact_version` (+ `catalog_version`), all must match the paired rounds artifact exactly | The Connection Guesser rounds artifact, scheduled | `networked_players_contracts.connection_daily_manifest::connection_daily_manifest_failures` | `daily_manifest_check_job.py` | `/play/daily/` |
| Record Routes | `apps/web/public/data/routes/{universe,rounds}.v1.json` | `pool_version`, `artifact_version` (+ `catalog_version`) | One-hop dataset + catalog + release-format policy (bridge gating) | `networked_players_contracts.record_routes::record_routes_failures` | `record_routes_check_job.py` | `/play/routes/` |

Every `*_version`/`*_failures` pair above follows the same identity model established for
the Connection Guesser (ADR 0043): a `pool_version` changes only on membership change; an
`artifact_version` changes on ANY published-field change, including reordering. Regenerate
in the order the table implies (catalog first, everything else after) whenever the
catalog itself changes.

## Resource expectations

Real elapsed-time/memory/throughput figures for each of the runbooks above are recorded
in `docs/DATA_SIZING.md` (public, method + real observed numbers where a real run has
happened) and, for anything not yet summarized there, in `local/benchmarks/`/`local/jobs/`
(git-ignored, per ADR 0018 — ad hoc job-result numbers stay local, never transcribed into
a committed doc). Check `docs/DATA_SIZING.md` first; it is kept current for every real
generation run referenced by the runbooks above.

## Replicating datasets to worker caches (ADR 0025)

The master/coordination host's `local/processed/` is always the authoritative
copy. A worker's local cache is a disposable, verified replica — never
treated as a source of truth, and safe to delete and re-fetch at any time.

### Replicate to the x86 worker (full dataset, masters, or one-hop)

```bash
cd ~/networked-players
make deploy-catalog-data                     # prints the LAN URL to use below

make replicate-x86 DATASET=discogs         SNAPSHOT=20260601 CATALOG_DATA_URL=http://<lan-ip>:8791
make replicate-x86 DATASET=discogs-masters SNAPSHOT=20260601 CATALOG_DATA_URL=http://<lan-ip>:8791
make replicate-x86 DATASET=discogs-onehop  SNAPSHOT=20260601 CATALOG_DATA_URL=http://<lan-ip>:8791

make deploy-catalog-data ARGS=--down
```

### Verify an existing cache without re-fetching

```bash
make replicate-x86 DATASET=discogs SNAPSHOT=20260601 ARGS='-e verify_only=true'
```

### rsync fallback (x86 only, for a slow HTTP pull)

```bash
./scripts/replicate-rsync.sh discogs 20260601 <x86-worker-ssh-target> <remote-cache-root>
# then verify, per the reminder the script prints:
make replicate-x86 DATASET=discogs SNAPSHOT=20260601 ARGS='-e verify_only=true --limit <x86-worker-alias>'
```

### Replicate the one-hop dataset to a Pi (opt-in, always bounded)

Pi workers can only ever cache the one-hop dataset — `replicate-dataset-pi.yml`
has no `dataset` variable at all, and always enforces a pre-download byte
guard (2 GiB default) against the served manifest's total size. Trial against
one Pi first:

```bash
make deploy-catalog-data
make replicate-pi SNAPSHOT=20260601 CATALOG_DATA_URL=http://<lan-ip>:8791 ARGS='--limit <one-pi-alias>'
make deploy-catalog-data ARGS=--down
```

### Staleness

Datasets are immutable by convention, so a worker cache never goes stale
*across* snapshots — a new snapshot is just a new directory. **Re-ingesting
the same snapshot date does invalidate any cache built from it**; nothing
detects this automatically, so re-run the replication above after any such
re-ingest.

## Which host runs what

- **Workstation / coordination host:** manifest, download, full parse, validation, canonical
  artifact retention. The Swarm manager; never a worker.
- **x86 worker (`x86_workers`, ADR 0022/0023):** a dedicated x86_64 Swarm worker; may hold a
  replicated dataset cache (see "Worker dataset cache" above) and takes on heavier RQ/Dask
  fleet work than the Pi's, at a higher-capability tier — never a full raw-dump download of
  its own, and never promoted to manager.
- **Raspberry Pi 3B workers:** only bounded, immutable, checksummed partitions — never the
  full raw dump. See [HARDWARE.md](HARDWARE.md) and the catalog package's resource posture.
- **Cohort resolution/scoring** ("Real cohort rehearsal" above) follows the same
  dataset-locality rule as one-hop expansion: run on whichever host has the relevant
  dataset locally, preferring the x86 worker for a real one-hop dataset.
  `draft-cohort-review`/`promote-playable-cohort` need no dataset at all (pure Python,
  JSON-in/JSON-out) and can run anywhere, including a developer machine. Pi workers run
  neither step.

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
