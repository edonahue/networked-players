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

    connection = duckdb.connect(database=":memory:")
    connection.read_parquet(release_glob).create_view("releases")
    connection.read_parquet(track_glob).create_view("tracks")
    connection.read_parquet(credit_glob).create_view("credits")

    metrics = {
        "release_rows": _scalar(connection, "SELECT count(*) FROM releases"),
        "distinct_release_ids": _scalar(
            connection, "SELECT count(DISTINCT release_id) FROM releases"
        ),
        "orphan_tracks": _scalar(
            connection, "SELECT count(*) FROM tracks t ANTI JOIN releases r USING (release_id)"
        ),
        "orphan_credits": _scalar(
            connection, "SELECT count(*) FROM credits c ANTI JOIN releases r USING (release_id)"
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
    failures = {
        key: value
        for key, value in metrics.items()
        if key
        in {
            "orphan_tracks",
            "orphan_credits",
            "invalid_linked_artist_ids",
            "missing_credit_scope",
        }
        and value
    }
    if metrics["release_rows"] != metrics["distinct_release_ids"]:
        failures["duplicate_release_ids"] = (
            metrics["release_rows"] - metrics["distinct_release_ids"]
        )
    if metrics["release_rows"] != manifest["counts"]["releases"]:
        failures["manifest_release_count_mismatch"] = metrics["release_rows"]
    if failures:
        raise ValidationError(json.dumps(failures, sort_keys=True))
    return metrics
