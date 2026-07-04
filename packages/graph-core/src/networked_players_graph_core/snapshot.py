"""Export a materialized co-credit adjacency snapshot from a credit dataset.

Unlike `challenge.py` (a small, curated, public web artifact),
`graph-snapshot-v1` is a full graph dump: every playable artist and every
co-credit edge within the traversal cap, over a snapshot that is typically
the one-hop working set. It is seed-derived when built from a one-hop
dataset and therefore private by location -- see the module docstring
pattern in `networked_players_catalog.discogs.onehop` -- output lives under
git-ignored `local/`, never committed or published.

Generation uses the same linked_credits/traversal_releases semantics as
`graph.CreditGraph` (playable-identity credits, non-individual IDs excluded,
`max_artists_per_release` caps which releases drive edges), reimplemented
here as direct SQL rather than built on an open CreditGraph, so this module
controls its own staging/atomic-write discipline independently.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from . import __version__
from .graph import NON_INDIVIDUAL_ARTIST_IDS, read_parquet_sql

GRAPH_SNAPSHOT_SCHEMA_VERSION = 1
GRAPH_SNAPSHOT_TABLES = ("artists", "edges")


class SnapshotError(RuntimeError):
    """Raised when a graph snapshot cannot be exported."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_graph_snapshot(
    dataset_root: Path,
    output_root: Path,
    *,
    memory_limit: str = "1GB",
    threads: int = 2,
    max_artists_per_release: int = 50,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export the artists/edges tables; returns the written manifest."""
    dataset_root = Path(dataset_root)
    output_root = Path(output_root)

    source_manifest_path = dataset_root / "manifest.json"
    if not source_manifest_path.is_file():
        raise SnapshotError(f"no manifest.json under {dataset_root} -- not a parsed dataset")
    source_manifest = json.loads(source_manifest_path.read_text())
    snapshot_date = str(source_manifest["snapshot_date"])

    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"snapshot already exists: {final_root}")

    credits_glob = str(dataset_root / "table=credits" / "*.parquet")

    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)

    try:
        connection = duckdb.connect(database=":memory:")
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute(f"SET threads = {int(threads)}")

        try:
            connection.execute(
                f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}"
            )
        except duckdb.IOException as exc:
            raise SnapshotError(f"could not open dataset at {dataset_root}: {exc}") from exc

        non_individual = ", ".join(str(i) for i in sorted(NON_INDIVIDUAL_ARTIST_IDS))
        connection.execute(
            "CREATE VIEW linked_credits AS "
            "SELECT release_id, artist_id, name FROM credits "
            "WHERE playable_identity AND artist_id IS NOT NULL AND artist_id > 0 "
            f"AND artist_id NOT IN ({non_individual})"
        )
        connection.execute(
            "CREATE TEMP TABLE traversal_releases AS "
            "SELECT release_id FROM linked_credits GROUP BY release_id "
            f"HAVING count(DISTINCT artist_id) BETWEEN 2 AND {int(max_artists_per_release)}"
        )

        table_sources = {
            "artists": (
                "SELECT artist_id, name FROM linked_credits "
                "GROUP BY artist_id, name "
                "QUALIFY row_number() OVER "
                "(PARTITION BY artist_id ORDER BY count(*) DESC, name) = 1"
            ),
            "edges": (
                "SELECT a.artist_id AS artist_a_id, b.artist_id AS artist_b_id, "
                "list(DISTINCT a.release_id ORDER BY a.release_id) AS release_ids, "
                "count(DISTINCT a.release_id) AS release_count "
                "FROM linked_credits a "
                "JOIN linked_credits b USING (release_id) "
                "JOIN traversal_releases USING (release_id) "
                "WHERE a.artist_id < b.artist_id "
                "GROUP BY a.artist_id, b.artist_id"
            ),
        }
        table_order = {
            "artists": "ORDER BY artist_id",
            "edges": "ORDER BY artist_a_id, artist_b_id",
        }

        counts: dict[str, int] = {}
        files: list[dict[str, object]] = []
        for table_name, select_sql in table_sources.items():
            table_dir = staging_root / f"table={table_name}"
            table_dir.mkdir(parents=True, exist_ok=True)
            out_path = table_dir / "part-00000.parquet"
            connection.execute(
                f"COPY ({select_sql} {table_order[table_name]}) "
                f"TO '{out_path}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            rows = int(pq.ParquetFile(out_path).metadata.num_rows)
            counts[table_name] = rows
            files.append(
                {
                    "path": str(out_path.relative_to(staging_root)),
                    "size_bytes": out_path.stat().st_size,
                    "sha256": _sha256(out_path),
                    "rows": rows,
                }
            )

        if counts["artists"] == 0:
            raise SnapshotError("no playable artists found -- refusing to write an empty snapshot")

        connection.close()

        manifest: dict[str, Any] = {
            "dataset_manifest_version": 1,
            "schema_version": GRAPH_SNAPSHOT_SCHEMA_VERSION,
            "graph_core_version": __version__,
            "source": "Materialized co-credit adjacency over a Discogs credit dataset",
            "snapshot_date": snapshot_date,
            "generated_at": datetime.now(UTC).isoformat(),
            "compression": "zstd",
            "counts": counts,
            "files": files,
            "generation": {
                "method": (
                    "linked_credits/traversal_releases co-credit adjacency -- the same "
                    "semantics as networked_players_graph_core.graph.CreditGraph"
                ),
                "max_artists_per_release": max_artists_per_release,
                "source_manifest_sha256": _sha256(source_manifest_path),
                "source_expansion": source_manifest.get("expansion"),
            },
        }
        (staging_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        if final_root.exists():
            shutil.rmtree(final_root)
        staging_root.replace(final_root)
        return manifest
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
