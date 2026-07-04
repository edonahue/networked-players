"""Re-verify a published challenge.v2 artifact's evidence against the real dataset.

The reference implementation for this check. A self-contained duckdb+stdlib
mirror runs on Pi workers (infra/ansible/files/verify_challenge_job.py, since
a Pi's lean venv has no graph-core installed) -- that file's header comment
names this module as the source of truth; keep the two in sync by hand.

This is the first production-shaped Pi job (docs/DISCOGS_INGESTION.md's
"challenge batches" hardware profile): given a small, shippable artifact and
the Pi-local one-hop cache, confirm every published hop's evidence actually
exists in the dataset, rather than trusting the artifact blindly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

_EVIDENCE_MATCH_COLUMNS = ("release_id", "artist_id", "credit_scope", "role_text", "name")


class VerifyDatasetError(RuntimeError):
    """Raised when the dataset needed to verify an artifact can't be opened."""


def verify_challenge_evidence(
    artifact: dict[str, Any],
    dataset_root: Path,
    *,
    path_ids: list[str] | None = None,
    memory_limit: str = "256MB",
    threads: int = 1,
) -> dict[str, Any]:
    """Check every selected path's hops against the real credits table.

    For each hop: (a) both endpoint artists have a playable_identity credit
    row on that release, and (b) every embedded evidence credit row the
    artifact publishes for that hop exists verbatim in the dataset. Failures
    are collected and returned, never raised -- the caller judges the report.
    """
    dataset_root = Path(dataset_root)
    if not (dataset_root / "manifest.json").exists():
        raise VerifyDatasetError(f"no manifest.json under {dataset_root}")

    connection = duckdb.connect(database=":memory:")
    connection.execute(f"SET memory_limit = '{memory_limit}'")
    connection.execute(f"SET threads = {int(threads)}")
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")
    try:
        connection.execute(f"CREATE VIEW credits AS SELECT * FROM read_parquet('{credits_glob}')")
    except duckdb.IOException as exc:
        raise VerifyDatasetError(f"could not open dataset at {dataset_root}: {exc}") from exc

    releases_by_id = {r["release_id"]: r for r in artifact["releases"]}
    selected_paths = [p for p in artifact["paths"] if path_ids is None or p["id"] in path_ids]

    failures: list[str] = []
    hops_verified = 0
    evidence_rows_checked = 0

    for path in selected_paths:
        for hop in path["hops"]:
            release_id = hop["release_id"]
            endpoints = (hop["artist_a_id"], hop["artist_b_id"])

            linked_rows = connection.execute(
                "SELECT DISTINCT artist_id FROM credits "
                "WHERE release_id = ? AND artist_id IN (?, ?) AND playable_identity",
                [release_id, *endpoints],
            ).fetchall()
            linked_ids = {row[0] for row in linked_rows}
            for artist_id in endpoints:
                if artist_id not in linked_ids:
                    failures.append(
                        f"path {path['id']}: artist {artist_id} has no playable credit "
                        f"on release {release_id}"
                    )

            release = releases_by_id.get(release_id)
            if release is None:
                failures.append(f"path {path['id']}: release {release_id} not published")
                continue

            for evidence_row in release["credits"]:
                evidence_rows_checked += 1
                match = connection.execute(
                    "SELECT count(*) FROM credits "
                    "WHERE release_id = ? AND artist_id = ? AND credit_scope = ? "
                    "AND role_text IS NOT DISTINCT FROM ? AND name = ?",
                    [evidence_row[col] for col in _EVIDENCE_MATCH_COLUMNS],
                ).fetchone()
                if match is None or match[0] == 0:
                    failures.append(
                        f"path {path['id']}: evidence row for artist "
                        f"{evidence_row['artist_id']} on release {release_id} not found "
                        "verbatim in the dataset"
                    )

            hops_verified += 1

    connection.close()
    return {
        "paths_checked": len(selected_paths),
        "hops_verified": hops_verified,
        "evidence_rows_checked": evidence_rows_checked,
        "failures": failures,
    }
