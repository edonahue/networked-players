#!/usr/bin/env python3
"""Standalone challenge-evidence verification job body, for a Pi worker's RQ queue.

Self-contained (stdlib + duckdb only) on purpose -- a Pi's lean worker venv
(equip-workers.yml: redis/rq/duckdb, no lxml/pyarrow) can't import
networked_players_graph_core. This is a hand-maintained MIRROR of
networked_players_graph_core.verify.verify_challenge_evidence -- the real
reference implementation, which is tested normally under packages/graph-core.
If that module's check logic changes, mirror the change here too;
packages/graph-core/tests/test_verify_job_body.py cross-checks the two
against the same synthetic inputs to catch drift.

Deployed by infra/ansible/playbooks/deploy-verify-job.yml alongside a small
challenge.v2.json artifact, both placed at rq_jobs_dir. Enqueued by
scripts/enqueue_verify_challenge.py via
``Queue(...).enqueue("verify_challenge_job.verify_shard", artifact_path, path_ids)``.

Deliberately reads the dataset from CATALOG_DATA_DIR only (ADR 0025's
verified local cache) -- never CATALOG_DATA_URL. A Pi doing real verification
work should be checking evidence against its own bounded local cache, not
re-reading the dataset over the LAN for every job.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import duckdb


class VerifyDatasetError(RuntimeError):
    """Raised when the dataset needed to verify an artifact can't be opened."""


def _batch_check_linked_endpoints(
    connection: duckdb.DuckDBPyConnection, endpoint_checks: list[tuple[str, int, int]]
) -> set[tuple[int, int]]:
    """Which (release_id, artist_id) pairs among `endpoint_checks` have a
    real `playable_identity` credit row -- one query for every distinct pair
    across every hop, not one query per hop. Keep in sync with
    `_batch_check_evidence_rows` below and with
    `networked_players_graph_core.verify`'s reference implementation."""
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


def _dataset_root(snapshot_date: str) -> Path:
    cache_dir = os.environ.get("CATALOG_DATA_DIR")
    if not cache_dir:
        raise VerifyDatasetError("CATALOG_DATA_DIR is not set -- this job requires a local cache")
    root = Path(cache_dir) / "discogs-onehop" / f"snapshot={snapshot_date}"
    if not (root / ".verified.json").exists():
        raise VerifyDatasetError(f"{root} is not a validated cache (no .verified.json)")
    return root


def verify_shard(artifact_path: str, path_ids: list[str]) -> dict[str, Any]:
    """Verify exactly the given path_ids from the artifact at artifact_path.

    A relative artifact_path resolves against THIS file's own directory, not
    the process's cwd (unpredictable under systemd-run) -- the enqueuer
    always passes the relative filename "challenge.v2.json" since it can't
    know each worker's absolute rq_jobs_dir (ansible_env.HOME varies per
    host); deploy-verify-job.yml places the artifact right next to this
    script.
    """
    resolved_path = Path(artifact_path)
    if not resolved_path.is_absolute():
        resolved_path = Path(__file__).resolve().parent / resolved_path
    artifact = json.loads(resolved_path.read_text())
    snapshot_date = artifact["provenance"]["snapshot_date"]
    dataset_root = _dataset_root(snapshot_date)

    connection = duckdb.connect(database=":memory:")
    connection.execute("SET memory_limit = '256MB'")
    connection.execute("SET threads = 1")
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")
    try:
        # hive_partitioning=false: without it, DuckDB auto-detects this
        # dataset's own `snapshot=X/table=Y/` directory names as partition
        # columns and silently injects `snapshot`/`table` into every row --
        # see networked_players_graph_core.graph.read_parquet_sql, which
        # this self-contained mirror can't import.
        connection.execute(
            "CREATE VIEW credits AS SELECT * FROM "
            f"read_parquet('{credits_glob}', hive_partitioning = false)"
        )
    except duckdb.IOException as exc:
        raise VerifyDatasetError(f"could not open dataset at {dataset_root}: {exc}") from exc

    releases_by_id = {r["release_id"]: r for r in artifact["releases"]}
    selected_paths = [p for p in artifact["paths"] if p["id"] in path_ids]

    failures: list[str] = []
    hops_verified = 0
    evidence_rows_checked = 0

    # Collect every check this artifact needs up front, across every
    # selected path/hop, so the two loops below issue one batched query
    # each instead of one query per hop plus one query per evidence row --
    # on a published floor of "50+ one-hop, 20+ two-hop" paths, the old
    # per-item form issued thousands of sequential single-row queries on a
    # real 1GB-RAM Pi worker.
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


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Usage: verify_challenge_job.py <artifact_path> <comma-separated-path-ids>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    result = verify_shard(sys.argv[1], sys.argv[2].split(","))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
