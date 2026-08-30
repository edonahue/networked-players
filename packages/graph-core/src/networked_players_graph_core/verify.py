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

from .graph import read_parquet_sql


class VerifyDatasetError(RuntimeError):
    """Raised when the dataset needed to verify an artifact can't be opened."""


def _batch_check_linked_endpoints(
    connection: duckdb.DuckDBPyConnection, endpoint_checks: list[tuple[str, int, int]]
) -> set[tuple[int, int]]:
    """Which (release_id, artist_id) pairs among `endpoint_checks` have a
    real `playable_identity` credit row -- one query for every distinct pair
    across every hop, not one query per hop. Keep in sync with
    `_batch_check_evidence_rows` below and with
    `infra/ansible/files/verify_challenge_job.py`'s mirror."""
    distinct_pairs = sorted(
        {(release_id, artist_id) for _pid, release_id, artist_id in endpoint_checks}
    )
    if not distinct_pairs:
        return set()
    connection.execute("CREATE TEMP TABLE endpoint_pairs (release_id BIGINT, artist_id BIGINT)")
    try:
        connection.executemany("INSERT INTO endpoint_pairs VALUES (?, ?)", distinct_pairs)
        rows = connection.execute(
            "SELECT DISTINCT c.release_id, c.artist_id FROM credits c "
            "JOIN endpoint_pairs p ON c.release_id = p.release_id AND c.artist_id = p.artist_id "
            "WHERE c.playable_identity"
        ).fetchall()
    finally:
        connection.execute("DROP TABLE endpoint_pairs")
    return {(row[0], row[1]) for row in rows}


def _batch_check_evidence_rows(
    connection: duckdb.DuckDBPyConnection,
    evidence_checks: list[tuple[str, int, int, str, Any, str]],
) -> set[tuple[int, int, str, Any, str]]:
    """Which (release_id, artist_id, credit_scope, role_text, name) tuples
    among `evidence_checks` exist verbatim in `credits` -- one query for
    every distinct tuple across every hop's evidence rows, not one query
    per row. `role_text` is matched NULL-safely (`IS NOT DISTINCT FROM`,
    mirroring the original per-row query) since a release_artist-scope row
    can legitimately carry no role_text; every other column uses plain
    equality, also mirroring the original."""
    # Not sorted: role_text can be None mixed with real strings, which
    # Python's tuple comparison can't order -- only uniqueness matters here,
    # not a stable iteration order.
    distinct_tuples = list({t[1:] for t in evidence_checks})
    if not distinct_tuples:
        return set()
    connection.execute(
        "CREATE TEMP TABLE evidence_tuples "
        "(release_id BIGINT, artist_id BIGINT, credit_scope VARCHAR, "
        "role_text VARCHAR, name VARCHAR)"
    )
    try:
        connection.executemany(
            "INSERT INTO evidence_tuples VALUES (?, ?, ?, ?, ?)", distinct_tuples
        )
        rows = connection.execute(
            "SELECT DISTINCT e.release_id, e.artist_id, e.credit_scope, e.role_text, e.name "
            "FROM credits c JOIN evidence_tuples e ON "
            "c.release_id = e.release_id AND c.artist_id = e.artist_id "
            "AND c.credit_scope = e.credit_scope "
            "AND c.role_text IS NOT DISTINCT FROM e.role_text "
            "AND c.name = e.name"
        ).fetchall()
    finally:
        connection.execute("DROP TABLE evidence_tuples")
    return {(row[0], row[1], row[2], row[3], row[4]) for row in rows}


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
        connection.execute(f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}")
    except duckdb.IOException as exc:
        raise VerifyDatasetError(f"could not open dataset at {dataset_root}: {exc}") from exc

    releases_by_id = {r["release_id"]: r for r in artifact["releases"]}
    selected_paths = [p for p in artifact["paths"] if path_ids is None or p["id"] in path_ids]

    failures: list[str] = []
    hops_verified = 0
    evidence_rows_checked = 0

    # Collect every check this artifact needs up front, across every
    # selected path/hop, so the two loops below issue one batched query
    # each instead of one query per hop plus one query per evidence row --
    # on a published floor of "50+ one-hop, 20+ two-hop" paths, the old
    # per-item form issued thousands of sequential single-row queries on a
    # real 1GB-RAM Pi worker (this module's own header: "the first
    # production-shaped Pi job").
    endpoint_checks: list[tuple[str, int, int]] = []  # (path_id, release_id, artist_id)
    evidence_checks: list[tuple[str, int, int, str, Any, str]] = []
    # (path_id, release_id, artist_id, credit_scope, role_text, name)

    for path in selected_paths:
        for hop in path["hops"]:
            release_id = hop["release_id"]
            for artist_id in (hop["artist_a_id"], hop["artist_b_id"]):
                endpoint_checks.append((path["id"], release_id, artist_id))

            release = releases_by_id.get(release_id)
            if release is None:
                failures.append(f"path {path['id']}: release {release_id} not published")
                continue

            for evidence_row in release["credits"]:
                evidence_rows_checked += 1
                evidence_checks.append(
                    (
                        path["id"],
                        release_id,
                        evidence_row["artist_id"],
                        evidence_row["credit_scope"],
                        evidence_row["role_text"],
                        evidence_row["name"],
                    )
                )

            hops_verified += 1

    linked_pairs = _batch_check_linked_endpoints(connection, endpoint_checks)
    for path_id, release_id, artist_id in endpoint_checks:
        if (release_id, artist_id) not in linked_pairs:
            failures.append(
                f"path {path_id}: artist {artist_id} has no playable credit on release {release_id}"
            )

    matched_evidence = _batch_check_evidence_rows(connection, evidence_checks)
    for path_id, release_id, artist_id, credit_scope, role_text, name in evidence_checks:
        if (release_id, artist_id, credit_scope, role_text, name) not in matched_evidence:
            failures.append(
                f"path {path_id}: evidence row for artist {artist_id} on release "
                f"{release_id} not found verbatim in the dataset"
            )

    connection.close()
    return {
        "paths_checked": len(selected_paths),
        "hops_verified": hops_verified,
        "evidence_rows_checked": evidence_rows_checked,
        "failures": failures,
    }
