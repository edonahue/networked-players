# Discogs ingestion plan

## Goal

Turn a private list of owned Discogs release IDs into a reproducible, evidence-bearing catalog slice and eventually a broad music-credit graph. The private seed selects work; monthly catalog dumps provide durable public catalog facts; the API is reserved for explicit gaps, validation, or recent changes.

## Source roles

| Source | Project use | Retention | Publication posture |
| --- | --- | --- | --- |
| Private collection export | Select initial release IDs | Local only | Never publish membership or account fields |
| Monthly XML dumps | Canonical bulk catalog snapshot | Raw compressed object plus normalized snapshot | CC0 catalog facts, with provenance |
| Discogs API | Bounded gap filling and freshness checks | Minimal raw response cache | Follow current notice, linking, freshness, and restricted-data terms |

The bulk pipeline must not require an API token. API credentials and rate-limit state belong on the coordination host, not on Pi workers or in browser code.

## Initial vertical slice

```text
private release-ID seed (local)
        │
        ▼
verified monthly manifest ──► compressed releases.xml.gz
        │                              │
        │                              ▼
        │                    streaming lxml.iterparse
        │                              │
        ▼                              ▼
provenance manifest          release / track / credit rows
                                       │
                                       ▼
                          chunked Zstandard Parquet
                                       │
                          ┌────────────┴────────────┐
                          ▼                         ▼
                    DuckDB checks           collection + one-hop filter
                                                    │
                                                    ▼
                                        evidence graph / static challenge
```

The initial implementation parses releases. The downloader and manifest understand all four dump kinds so artists, masters, and labels can be added without redesigning acquisition.

## Download behavior

1. Create a monthly manifest from an explicit snapshot date.
2. Download into a `.part` file and resume only after a valid HTTP `206` response.
3. Refuse size or SHA-256 mismatches.
4. Atomically rename only a verified file.
5. Record byte size, checksum, ETag when available, and download time in the manifest.
6. Keep at most the retention set described in `DATA_SIZING.md`.

Anonymous bucket listing is not a correctness dependency. During this research, clean GitHub-hosted runners received HTTP 403 for the landing object, listing operations, and known object paths. The code therefore accepts an explicit official URL in the manifest and reports access failures rather than treating `403` as “snapshot absent.”

## Parsing and normalization

The parser opens gzip directly and listens for completed `<release>` elements. It clears each processed element and prior siblings so memory tracks the active XML subtree rather than the total dump size. It does **not** materialize the expanded XML file.

The initial normalized contract preserves:

- Release ID, master relationship, status, title, country, date, and data quality.
- Ordered tracks with Discogs position text rather than assuming a numeric track number.
- Main artists and extra artists at both release and track scope.
- PAN identity through `artist_id` and credited ANV text separately.
- Exact role text; taxonomy and role splitting are later transforms.
- Non-linked names as evidence while excluding them from playable identity nodes.
- Snapshot date, source URL, parser version, schema version, file checksums, and row counts.

A documented credit proves participation on a release or track. It does not prove influence, friendship, or stylistic lineage.

## Hardware execution profiles

| Role | Appropriate work | Initial limits |
| --- | --- | --- |
| Optional workstation-class build node | Full release parse, full-catalog transforms, Parquet compaction, benchmarks | Preferred full-ingest host when available; local NVMe; bounded process count |
| SSD-backed coordination host | Manifest/download control, small slices, canonical artifact registry, DuckDB validation, publication | Keep free-space guardrails; no unbounded concurrent full parses |
| Three active Pi 3B workers | Checksummed partition validation, role summaries, challenge batches (see `verify_challenge_job.py`), graph tests | One worker process each; inputs normally below 128–256 MB; no raw full release dump |
| Static hosting | Versioned challenges and compact public data | No dependency on the home cluster |

The first parser is intentionally single-process. Gzip/XML parsing is sequential and releases vary dramatically in size. Safe parallelism starts after normalization, when independent Parquet partitions can be distributed without repeatedly inflating the same raw object.

## One-hop construction

The practical first graph does not need every Discogs release:

1. Load private seed release IDs locally.
2. Extract the seed releases and their linked credited artist IDs.
3. Build an artist-ID frontier.
4. Scan the release table to retain releases containing a frontier artist.
5. Preserve every retained release and credit row needed to prove each edge.
6. Generate a compact graph snapshot and manually verify at least one path.

The first full sequential parse completed 2026-07-02 (19,192,301 releases from the June 2026 snapshot, validated clean — see `docs/BUILD_PLAN.md` Milestone 3 and `docs/DATA_SIZING.md`'s "Full unbounded run: complete"), so a reusable release-to-artist index can now be built from it. Later monthly refreshes should compare snapshot manifests and rebuild immutable artifacts rather than editing Parquet files in place.

## Recovery and reproducibility

Raw compressed dumps are immutable inputs. Normalized datasets live under `snapshot=YYYYMMDD`, publish only after validation, and are never mutated in place. A failed staging directory can be deleted. The previous canonical snapshot remains available for rollback. PostgreSQL may index a selected snapshot later, but it is not the only copy of catalog truth.

### Atomic parts and resumable release parsing

`parse-releases` is a long single-stream job, so its output is built to survive interruption:

- **Atomic parts.** Every Parquet part is written to a hidden temp name (`.part-NNNNN.parquet.tmp`) in
  its table directory, fsynced, renamed to `part-NNNNN.parquet`, and the directory is fsynced where the
  platform allows. A file under a final part name is always complete.
- **Progress record.** `progress.json` in the staging directory is replaced atomically (write-temp,
  fsync, rename) after each completed part. It records the run parameters (snapshot, source URL,
  `--chunk-releases`, `--max-releases`, schema and parser versions), the input identity (file name,
  size, and the download manifest's sha256 when `--input-manifest` is given -- the dump itself is never
  re-hashed), every completed part (`path`, `size_bytes`, `sha256`, `rows`), and the stream position:
  `releases_persisted` (the release ordinal reached), `last_release_id`, and `release_id_digest`
  (SHA-256 over the ordered ids of every persisted release). The record is committed after a part's
  write finishes, so at most the one part in flight at a kill is unrecorded and gets redone.
- **`parse-releases --resume`.** The dump is one gzip XML stream and cannot be seeked, so resume is
  *re-read and skip*: it validates the staging directory, re-streams the dump from the start,
  reading only the `id` of each already-persisted release (nothing is normalized, hashed or retained;
  elements are cleared as usual, so memory stays bounded), checks the count, last `release_id` and
  digest against the record, then continues writing at the next part index. Final output is identical
  to an uninterrupted run (same parts, rows and sha256s; only `generated_at` in `manifest.json`
  differs). Parquet part bytes are reproducible (tests assert byte equality) because the writer embeds no timestamps, only its library version in `created_by`, so this holds within one pyarrow version.
- **What resume does not save.** It saves the normalization, Parquet-write and hashing work of the
  completed portion. It does not save the decompress and XML-parse cost of re-reading that portion.
  No speed-up figure is claimed; measure on your own hardware (results stay local, ADR 0018).

Resume refuses, leaving the staging directory untouched, when: there is no staging directory for the
snapshot; there is more than one (all are named); `progress.json` is missing, corrupt or inconsistent;
a recorded part is missing or differs in size or sha256; a parameter (`--chunk-releases`,
`--max-releases`, source URL, schema or parser version) differs from the original run; the input's
file name or size differs, or its sha256 differs from the one recorded from the download manifest; or
the input's first `releases_persisted` ids do not match (a different, shorter or re-downloaded dump).
Files in the staging directory that the record does not list (temp files, a complete-but-unrecorded
part, a stale `manifest.json`) are deleted with a logged line. A run without `--resume` refuses to
start while a staging directory for the snapshot exists, and names `--resume` and the recovery check.

`--max-releases` counts release ordinals from the start of the stream, so a bounded run resumes with
the same cap and stops at the same release. An ordinary exception (for example malformed XML) still
removes the staging directory, resumed or not; only a hard kill, power loss or Ctrl-C leaves it for
resume. Masters and artist-relations parsing get atomic part writes but no resume.
