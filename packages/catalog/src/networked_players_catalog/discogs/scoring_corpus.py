"""Bounded "scoring corpus": the one-hop corpus plus the rows of every
candidate release, extracted from the FULL parsed corpus (Campaign Atlas
Round 2, step R2-2).

Why this exists: theme candidates (`build-theme-candidates`) are found in the
full corpus, but `score-expansion-candidates` reads credits through
`--onehop-root`, and the theme albums are not in the one-hop corpus. The full
corpus is ~12 GB and cannot be replicated to a worker, so scoring against it
is coordination-host-only and heavy. This module writes a small corpus that
is provably sufficient for the scorer.

What the scorer reads from the corpus (`score_expansion_candidates` through
`CreditGraph`, all keyed by candidate master / release id):

- `releases WHERE master_id = <candidate master>` (`release_ids_for_master`);
- `releases WHERE release_id IN <those>` (`releases_for_ids`, release year);
- `credits WHERE release_id IN <selected main releases>`
  (`credit_rows_for_releases`).

The selected main release is either the master's own `main_release_id` or one
of the releases under the master. `bridge_span` reads only the published
pathfinding graph JSON, never the corpus. So NO credit of any performer on any
OTHER release is read, and no performer-set expansion is needed. The release
set is therefore: every release whose `master_id` is a candidate master, plus
each candidate master's `main_release_id` (masters dataset). All four tables
(releases, tracks, credits, release_formats) are extracted for it, so every
other `CreditGraph` read for those releases also matches the full corpus.

Layout: the one-hop parquet files are linked (hard link, else copied)
unchanged, and the extract is one extra `part-extra.parquet` per table holding
only releases the one-hop corpus does not already contain. A one-hop corpus
retains every row of each retained release (see `onehop.py`), so for a
release in both, the one-hop rows are already complete; nothing is
deduplicated or rewritten and the 700+ MB credits file is not re-sorted. The
self-check below verifies per-release credit counts against the full corpus.
Written to a staging directory and renamed into place atomically.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from networked_players_catalog import __version__

from .parquet import SCHEMA_VERSION, _sha256

# Tables extracted by release_id. `frontier_artists`/`seed_releases` are
# one-hop provenance tables the scorer never reads; they are linked through so
# the layout stays a superset of the one-hop corpus.
EXTRACTED_TABLES = ("releases", "tracks", "credits", "release_formats")
PASSTHROUGH_TABLES = ("frontier_artists", "seed_releases")

_ORDER = {
    "releases": "ORDER BY release_id",
    "release_formats": "ORDER BY release_id, format_index",
    "tracks": "ORDER BY ALL",
    "credits": "ORDER BY ALL",
}


class ScoringCorpusError(RuntimeError):
    """Raised when the scoring corpus cannot be built safely."""


def _rp(glob: str) -> str:
    return f"read_parquet('{glob}', hive_partitioning = false)"


def _progress(quiet: bool, message: str) -> None:
    if not quiet:
        print(message, file=sys.stderr)


def _read_manifest(root: Path, label: str) -> dict[str, object]:
    path = root / "manifest.json"
    if not path.is_file():
        raise ScoringCorpusError(f"no manifest.json under {label} {root}")
    manifest: dict[str, object] = json.loads(path.read_text())
    return manifest


def _table_files(root: Path, table: str) -> list[Path]:
    directory = root / f"table={table}"
    return sorted(directory.glob("*.parquet")) if directory.is_dir() else []


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _scalar(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise ScoringCorpusError(f"query returned no row: {query}")
    return int(row[0])


def build_scoring_corpus(
    onehop_root: Path,
    full_root: Path,
    masters_root: Path,
    candidates_path: Path,
    output_root: Path,
    *,
    memory_limit: str = "2GB",
    threads: int = 2,
    overwrite: bool = False,
    quiet: bool = False,
) -> dict[str, object]:
    """Write `output_root/snapshot=<date>` and return its manifest."""
    onehop_manifest = _read_manifest(onehop_root, "--onehop-root")
    full_manifest = _read_manifest(full_root, "--full-root")
    masters_manifest = _read_manifest(masters_root, "--masters-root")
    snapshot_date = str(full_manifest["snapshot_date"])
    for label, manifest in (("onehop", onehop_manifest), ("masters", masters_manifest)):
        if str(manifest.get("snapshot_date")) != snapshot_date:
            raise ScoringCorpusError(
                f"{label} snapshot_date {manifest.get('snapshot_date')!r} does not match "
                f"full corpus snapshot_date {snapshot_date!r} -- mismatched snapshots refused"
            )
    for label, manifest in (("full corpus", full_manifest), ("one-hop corpus", onehop_manifest)):
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ScoringCorpusError(
                f"{label} schema_version={manifest.get('schema_version')!r}; "
                f"this build writes {SCHEMA_VERSION}"
            )
    recorded_source = (onehop_manifest.get("expansion") or {}).get("source_manifest_sha256")  # type: ignore[attr-defined]
    if recorded_source is not None and recorded_source != _sha256(full_root / "manifest.json"):
        raise ScoringCorpusError(
            "one-hop manifest's source_manifest_sha256 does not match the full corpus manifest "
            "-- the one-hop corpus was not derived from this full corpus"
        )

    candidates = json.loads(candidates_path.read_text())
    if not isinstance(candidates, list):
        raise ScoringCorpusError("--candidates must be a JSON list of rows carrying master_id")
    master_ids = sorted({int(row["master_id"]) for row in candidates})
    if not master_ids:
        raise ScoringCorpusError("--candidates holds no master_id; nothing to extract")
    candidates_sha256 = hashlib.sha256(candidates_path.read_bytes()).hexdigest()

    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")

    onehop_files = {t: _table_files(onehop_root, t) for t in EXTRACTED_TABLES + PASSTHROUGH_TABLES}
    full_files = {t: _table_files(full_root, t) for t in EXTRACTED_TABLES}
    for table in ("releases", "tracks", "credits"):
        if not onehop_files[table] or not full_files[table]:
            raise ScoringCorpusError(f"table={table} missing from one-hop or full corpus")
    include_formats = bool(full_files["release_formats"])
    if onehop_files["release_formats"] and not include_formats:
        raise ScoringCorpusError("one-hop has release_formats but the full corpus does not")
    tables = [t for t in EXTRACTED_TABLES if t != "release_formats" or include_formats]

    output_root.mkdir(parents=True, exist_ok=True)
    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir()
    spill_dir = staging_root / ".duckdb-tmp"
    spill_dir.mkdir()
    try:
        connection = duckdb.connect(database=":memory:")
        connection.execute(f"SET memory_limit='{memory_limit}'")
        connection.execute(f"SET threads={int(threads)}")
        connection.execute(f"SET temp_directory='{spill_dir}'")

        full_glob = {t: str(full_root / f"table={t}" / "*.parquet") for t in EXTRACTED_TABLES}
        onehop_glob = {t: str(onehop_root / f"table={t}" / "*.parquet") for t in EXTRACTED_TABLES}

        connection.execute("CREATE TEMP TABLE candidate_masters(master_id BIGINT)")
        connection.executemany(
            "INSERT INTO candidate_masters VALUES (?)", [(m,) for m in master_ids]
        )
        # One pass over the full releases table (two narrow columns) plus the
        # candidate masters' own main_release_id, so every release the scorer
        # can select as a main release is present even if its releases row
        # carries a different/NULL master_id.
        _progress(quiet, "scoring corpus: resolving candidate masters to releases...")
        masters_glob = str(masters_root / "table=masters" / "*.parquet")
        connection.execute(
            f"""
            CREATE TEMP TABLE candidate_releases AS
            SELECT release_id FROM {_rp(full_glob["releases"])}
            WHERE master_id IN (SELECT master_id FROM candidate_masters)
            UNION
            SELECT main_release_id FROM {_rp(masters_glob)}
            WHERE master_id IN (SELECT master_id FROM candidate_masters)
              AND main_release_id IS NOT NULL
            """
        )
        connection.execute(
            "CREATE TEMP TABLE extra_releases AS "
            "SELECT c.release_id FROM candidate_releases c "
            f"WHERE c.release_id IN (SELECT release_id FROM {_rp(full_glob['releases'])}) "
            f"AND c.release_id NOT IN (SELECT release_id FROM {_rp(onehop_glob['releases'])})"
        )
        candidate_release_count = _scalar(connection, "SELECT count(*) FROM candidate_releases")
        extra_release_count = _scalar(connection, "SELECT count(*) FROM extra_releases")
        _progress(
            quiet,
            f"scoring corpus: {candidate_release_count} candidate releases, "
            f"{extra_release_count} not already in the one-hop corpus",
        )

        for table in tables:
            table_dir = staging_root / f"table={table}"
            table_dir.mkdir()
            for index, source in enumerate(onehop_files.get(table, [])):
                _link_or_copy(source, table_dir / f"part-{index:05d}.parquet")
            extra_path = table_dir / "part-extra.parquet"
            connection.execute(
                f"COPY (SELECT t.* FROM {_rp(full_glob[table])} t "
                "WHERE t.release_id IN (SELECT release_id FROM extra_releases) "
                f"{_ORDER[table]}) TO '{extra_path}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 6, ROW_GROUP_SIZE 50000)"
            )
            _progress(quiet, f"scoring corpus: extracted table={table}")
        for table in PASSTHROUGH_TABLES:
            if onehop_files[table]:
                table_dir = staging_root / f"table={table}"
                table_dir.mkdir()
                for index, source in enumerate(onehop_files[table]):
                    _link_or_copy(source, table_dir / f"part-{index:05d}.parquet")

        # Self-check before the rename: every candidate release that exists in
        # the full corpus is now present exactly once, with the full corpus's
        # own credit row count.
        staged_releases = str(staging_root / "table=releases" / "*.parquet")
        missing = _scalar(
            connection,
            "SELECT count(*) FROM candidate_releases c WHERE c.release_id IN "
            f"(SELECT release_id FROM {_rp(full_glob['releases'])}) AND c.release_id NOT IN "
            f"(SELECT release_id FROM {_rp(staged_releases)})",
        )
        duplicated = _scalar(
            connection,
            f"SELECT count(*) FROM (SELECT release_id FROM {_rp(staged_releases)} "
            "GROUP BY release_id HAVING count(*) > 1)",
        )
        mismatches: dict[str, int] = {}
        for table in ("credits", "tracks", "release_formats"):
            if table not in tables:
                continue
            staged = str(staging_root / f"table={table}" / "*.parquet")
            mismatches[f"{table}_count_mismatch_vs_full"] = _scalar(
                connection,
                f"""
                SELECT count(*) FROM (
                  SELECT release_id, count(*) n FROM {_rp(full_glob[table])}
                  WHERE release_id IN (SELECT release_id FROM candidate_releases)
                  GROUP BY release_id
                ) f FULL JOIN (
                  SELECT release_id, count(*) n FROM {_rp(staged)}
                  WHERE release_id IN (SELECT release_id FROM candidate_releases)
                  GROUP BY release_id
                ) s USING (release_id)
                WHERE f.n IS DISTINCT FROM s.n
                """,
            )
        if missing or duplicated or any(mismatches.values()):
            raise ScoringCorpusError(
                "scoring-corpus self-check failed: "
                + json.dumps(
                    {
                        "candidate_releases_missing": missing,
                        "duplicated_release_ids": duplicated,
                        **mismatches,
                    },
                    sort_keys=True,
                )
            )
        connection.close()
        shutil.rmtree(spill_dir, ignore_errors=True)

        counts: dict[str, int] = {}
        files: list[dict[str, object]] = []
        for table in tables + [t for t in PASSTHROUGH_TABLES if onehop_files[t]]:
            for path in sorted((staging_root / f"table={table}").glob("*.parquet")):
                rows = int(pq.ParquetFile(path).metadata.num_rows)
                counts[table] = counts.get(table, 0) + rows
                files.append(
                    {
                        "path": str(path.relative_to(staging_root)),
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                        "rows": rows,
                    }
                )

        corpus_manifest: dict[str, object] = {
            "dataset_manifest_version": 1,
            "schema_version": SCHEMA_VERSION,
            "parser_version": __version__,
            "source": "Discogs monthly data dumps (bounded scoring corpus)",
            "source_url": full_manifest.get("source_url"),
            "snapshot_date": snapshot_date,
            "generated_at": datetime.now(UTC).isoformat(),
            "compression": "zstd",
            "counts": counts,
            "files": files,
            "expansion": {
                "kind": "scoring-corpus",
                "source_snapshot_date": snapshot_date,
                "onehop_manifest_sha256": _sha256(onehop_root / "manifest.json"),
                "full_corpus_manifest_sha256": _sha256(full_root / "manifest.json"),
                "masters_manifest_sha256": _sha256(masters_root / "manifest.json"),
                "candidates_sha256": candidates_sha256,
                "candidate_master_count": len(master_ids),
                "candidate_release_count": candidate_release_count,
                "extra_release_count": extra_release_count,
            },
        }
        (staging_root / "manifest.json").write_text(
            json.dumps(corpus_manifest, indent=2, sort_keys=True) + "\n"
        )
        backup: Path | None = None
        if final_root.exists():
            backup = final_root.with_name(f".{final_root.name}.old-{uuid.uuid4().hex}")
            final_root.rename(backup)
        try:
            staging_root.replace(final_root)
        except BaseException:
            if backup is not None and not final_root.exists():
                backup.rename(final_root)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return corpus_manifest
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
