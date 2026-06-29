# Catalog package

This package is the first source-specific implementation in Networked Players. It provides a bounded vertical slice for acquiring and normalizing a Discogs **release** dump while keeping the private collection seed outside Git.

## Implemented in this scaffold

- deterministic monthly manifest generation for all four dump kinds;
- resumable, atomic downloads with SHA-256 and size verification;
- streaming `.xml.gz` release parsing with `lxml.iterparse`;
- release, track, and credit tables that preserve release-level evidence;
- linked versus non-linked contributor handling;
- chunked Zstandard Parquet output with a versioned dataset manifest;
- DuckDB validation of identity and evidence invariants;
- deterministic synthetic tests that require no Discogs credentials or live network.

The artists, labels, and masters objects are represented in the manifest, but their parsers are intentionally deferred. Release credits are the shortest path to the first collection-derived, evidence-backed challenge.

## Quick start

```bash
uv sync --extra dev

uv run networked-players-catalog manifest \
  --snapshot 20260501 \
  --output local/manifests/discogs-20260501.json

uv run networked-players-catalog download \
  --manifest local/manifests/discogs-20260501.json \
  --kind releases \
  --raw-dir local/raw/discogs

uv run networked-players-catalog parse-releases \
  --input local/raw/discogs/20260501/discogs_20260501_releases.xml.gz \
  --snapshot 20260501 \
  --source-url https://discogs-data-dumps.s3.us-west-2.amazonaws.com/data/2026/discogs_20260501_releases.xml.gz \
  --output-root local/processed/discogs \
  --max-releases 10000

uv run networked-players-catalog validate \
  --dataset local/processed/discogs/snapshot=20260501
```

The default object URL follows the public monthly naming convention. Discogs or its storage provider may reject listing or direct access from some networks; a manifest can be edited to use an explicitly obtained official URL without changing the parser.

## Output tables

### `releases`

One row per release, including source snapshot, release and master IDs, title, country, date, status, data quality, and evidence URL.

### `tracks`

One row per ordered track with position, title, and duration.

### `credits`

One row per release or track artist/credit. `credit_scope` distinguishes `release_artist`, `release_credit`, `track_artist`, and `track_credit`. Original role text and ANV are preserved. An absent or zero artist ID is retained as evidence with `is_linked=false` and `playable_identity=false`.

## Resource posture

The parser is deliberately streaming and single-process. Parallelism belongs after parsing, over immutable Parquet partitions. Full release conversion should run on the optional workstation when practical; the coordination host can run small slices and retain canonical artifacts. A Pi 3B worker should receive only bounded, checksummed partitions and run one worker process at a time.
