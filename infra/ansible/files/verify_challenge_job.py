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

_EVIDENCE_MATCH_COLUMNS = ("release_id", "artist_id", "credit_scope", "role_text", "name")


class VerifyDatasetError(RuntimeError):
    """Raised when the dataset needed to verify an artifact can't be opened."""


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
        connection.execute(f"CREATE VIEW credits AS SELECT * FROM read_parquet('{credits_glob}')")
    except duckdb.IOException as exc:
        raise VerifyDatasetError(f"could not open dataset at {dataset_root}: {exc}") from exc

    releases_by_id = {r["release_id"]: r for r in artifact["releases"]}
    selected_paths = [p for p in artifact["paths"] if p["id"] in path_ids]

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
