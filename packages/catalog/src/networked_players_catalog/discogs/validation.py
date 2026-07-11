"""DuckDB validation for a normalized release slice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb


class ValidationError(RuntimeError):
    """Raised when normalized data violates a project invariant."""


def _scalar(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise ValidationError(f"query returned no row: {query}")
    return int(row[0])


def validate_dataset(dataset_root: Path) -> dict[str, Any]:
    manifest = json.loads((dataset_root / "manifest.json").read_text())
    release_glob = str(dataset_root / "table=releases" / "*.parquet")
    track_glob = str(dataset_root / "table=tracks" / "*.parquet")
    credit_glob = str(dataset_root / "table=credits" / "*.parquet")
    format_glob = str(dataset_root / "table=release_formats" / "*.parquet")

    connection = duckdb.connect(database=":memory:")
    connection.read_parquet(release_glob).create_view("releases")
    connection.read_parquet(track_glob).create_view("tracks")
    connection.read_parquet(credit_glob).create_view("credits")
    connection.read_parquet(format_glob).create_view("release_formats")

    metrics = {
        "release_rows": _scalar(connection, "SELECT count(*) FROM releases"),
        "track_rows": _scalar(connection, "SELECT count(*) FROM tracks"),
        "credit_rows": _scalar(connection, "SELECT count(*) FROM credits"),
        "release_format_rows": _scalar(connection, "SELECT count(*) FROM release_formats"),
        "distinct_release_ids": _scalar(
            connection, "SELECT count(DISTINCT release_id) FROM releases"
        ),
        "orphan_tracks": _scalar(
            connection, "SELECT count(*) FROM tracks t ANTI JOIN releases r USING (release_id)"
        ),
        "orphan_credits": _scalar(
            connection, "SELECT count(*) FROM credits c ANTI JOIN releases r USING (release_id)"
        ),
        "orphan_release_formats": _scalar(
            connection,
            "SELECT count(*) FROM release_formats f ANTI JOIN releases r USING (release_id)",
        ),
        "invalid_linked_artist_ids": _scalar(
            connection,
            "SELECT count(*) FROM credits "
            "WHERE is_linked AND (artist_id IS NULL OR artist_id <= 0)",
        ),
        "missing_credit_scope": _scalar(
            connection,
            "SELECT count(*) FROM credits WHERE credit_scope IS NULL OR credit_scope = ''",
        ),
    }
    failures: dict[str, object] = {
        key: value
        for key, value in metrics.items()
        if key
        in {
            "orphan_tracks",
            "orphan_credits",
            "orphan_release_formats",
            "invalid_linked_artist_ids",
            "missing_credit_scope",
        }
        and value
    }
    if metrics["release_rows"] != metrics["distinct_release_ids"]:
        failures["duplicate_release_ids"] = (
            metrics["release_rows"] - metrics["distinct_release_ids"]
        )

    manifest_counts = manifest.get("counts")
    if not isinstance(manifest_counts, dict):
        failures["manifest_counts_invalid"] = manifest_counts
    else:
        for table_name, metric_name in (
            ("releases", "release_rows"),
            ("tracks", "track_rows"),
            ("credits", "credit_rows"),
            ("release_formats", "release_format_rows"),
        ):
            expected = manifest_counts.get(table_name)
            actual = metrics[metric_name]
            if not isinstance(expected, int):
                failures[f"manifest_{table_name}_count_invalid"] = expected
            elif actual != expected:
                failures[f"manifest_{table_name}_count_mismatch"] = {
                    "expected": expected,
                    "actual": actual,
                }

    if failures:
        raise ValidationError(json.dumps(failures, sort_keys=True))
    return metrics


def validate_master_dataset(dataset_root: Path) -> dict[str, Any]:
    """Invariants for a parsed masters dataset (MASTER_SCHEMA_VERSION).

    ``masters_missing_main_release`` is a reported metric, not a failure --
    the real dump has always carried ``main_release`` in observation
    (docs/discogs-data/raw-dump-schema.md), but that's an observed property
    of one snapshot, not a documented guarantee worth hard-failing on.
    """

    manifest = json.loads((dataset_root / "manifest.json").read_text())
    masters_glob = str(dataset_root / "table=masters" / "*.parquet")
    artists_glob = str(dataset_root / "table=master_artists" / "*.parquet")

    connection = duckdb.connect(database=":memory:")
    connection.read_parquet(masters_glob).create_view("masters")
    connection.read_parquet(artists_glob).create_view("master_artists")

    metrics = {
        "master_rows": _scalar(connection, "SELECT count(*) FROM masters"),
        "master_artist_rows": _scalar(connection, "SELECT count(*) FROM master_artists"),
        "distinct_master_ids": _scalar(connection, "SELECT count(DISTINCT master_id) FROM masters"),
        "orphan_master_artists": _scalar(
            connection,
            "SELECT count(*) FROM master_artists a ANTI JOIN masters m USING (master_id)",
        ),
        "invalid_linked_artist_ids": _scalar(
            connection,
            "SELECT count(*) FROM master_artists "
            "WHERE is_linked AND (artist_id IS NULL OR artist_id <= 0)",
        ),
        "masters_missing_main_release": _scalar(
            connection, "SELECT count(*) FROM masters WHERE main_release_id IS NULL"
        ),
    }
    failures: dict[str, object] = {
        key: value
        for key, value in metrics.items()
        if key in {"orphan_master_artists", "invalid_linked_artist_ids"} and value
    }
    if metrics["master_rows"] != metrics["distinct_master_ids"]:
        failures["duplicate_master_ids"] = metrics["master_rows"] - metrics["distinct_master_ids"]

    manifest_counts = manifest.get("counts")
    if not isinstance(manifest_counts, dict):
        failures["manifest_counts_invalid"] = manifest_counts
    else:
        for table_name, metric_name in (
            ("masters", "master_rows"),
            ("master_artists", "master_artist_rows"),
        ):
            expected = manifest_counts.get(table_name)
            actual = metrics[metric_name]
            if not isinstance(expected, int):
                failures[f"manifest_{table_name}_count_invalid"] = expected
            elif actual != expected:
                failures[f"manifest_{table_name}_count_mismatch"] = {
                    "expected": expected,
                    "actual": actual,
                }

    if failures:
        raise ValidationError(json.dumps(failures, sort_keys=True))
    return metrics
