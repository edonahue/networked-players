"""CLI round-trip for `score-expansion-candidates` (graph-expansion Phase 2,
plan section 5.2). The scoring math itself (eligibility, roster_size,
overlap_existing, new_performers, editorial/private-seed pass-through) is
thoroughly unit-tested with hand-verified expectations in
packages/graph-core/tests/test_score_expansion_candidates.py; this pins the
CLI wiring only: input-file loading (candidates, pathfinding-graph,
release-format-policy, exclusions, editorial/private-seed master-id lists),
output shape, and the local-only-output guard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import MASTER_SCHEMAS, SCHEMAS

SNAPSHOT_DATE = "20260601"


def _release(release_id: int, title: str, *, master_id: int | None = None) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": master_id,
        "master_is_main_release": True if master_id else None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int,
    *,
    artist_id: int,
    name: str,
    credit_scope: str = "release_artist",
    role_text: str | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": credit_scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _write_onehop_dataset(root: Path) -> Path:
    dataset_root = root / f"snapshot={SNAPSHOT_DATE}"
    (dataset_root / "table=releases").mkdir(parents=True)
    (dataset_root / "table=credits").mkdir(parents=True)
    (dataset_root / "table=tracks").mkdir(parents=True)

    # Master 900: eligible, roster Alice (existing) + Bob (new).
    # Master 901: ineligible (curated exclusion).
    releases = [
        _release(1, "First Light", master_id=900),
        _release(2, "Second Look", master_id=901),
    ]
    credits = [
        _credit(1, artist_id=100, name="Alice"),
        _credit(1, artist_id=200, name="Bob", credit_scope="track_artist"),
        _credit(2, artist_id=400, name="Dan"),
    ]
    pq.write_table(
        pa.Table.from_pylist(releases, schema=SCHEMAS["releases"]),
        dataset_root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(credits, schema=SCHEMAS["credits"]),
        dataset_root / "table=credits" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=SCHEMAS["tracks"]),
        dataset_root / "table=tracks" / "part-00000.parquet",
    )
    (dataset_root / "manifest.json").write_text(
        json.dumps({"snapshot_date": SNAPSHOT_DATE, "counts": {}})
    )
    return dataset_root


def _write_masters_dataset(root: Path) -> Path:
    masters_root = root / f"masters-snapshot={SNAPSHOT_DATE}"
    (masters_root / "table=masters").mkdir(parents=True)
    (masters_root / "table=master_artists").mkdir(parents=True)
    master_rows = [
        {
            "snapshot_date": SNAPSHOT_DATE,
            "master_id": master_id,
            "main_release_id": release_id,
            "title": title,
            "year": 1995,
            "genres": [],
            "styles": [],
            "data_quality": None,
            "source_url": f"https://example.invalid/master/{master_id}",
        }
        for master_id, release_id, title in [(900, 1, "First Light"), (901, 2, "Second Look")]
    ]
    pq.write_table(
        pa.Table.from_pylist(master_rows, schema=MASTER_SCHEMAS["masters"]),
        masters_root / "table=masters" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=MASTER_SCHEMAS["master_artists"]),
        masters_root / "table=master_artists" / "part-00000.parquet",
    )
    (masters_root / "manifest.json").write_text(
        json.dumps({"snapshot_date": SNAPSHOT_DATE, "counts": {"masters": 2}})
    )
    return masters_root


def _write_release_format_policy(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": SNAPSHOT_DATE,
                "allowed_release_ids": [1, 2],
                "allowed_release_count": 2,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
    return path


def _write_exclusions(path: Path, *, master_ids: list[int]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": "studio-album-v1",
                "snapshot_date": SNAPSHOT_DATE,
                "note": "test fixture",
                "exclusions": [{"master_id": mid} for mid in master_ids],
            }
        )
    )
    return path


def _write_pathfinding_graph(
    path: Path,
    *,
    existing_node_ids: list[int],
    offsets: list[int] | None = None,
    neighbors: list[int] | None = None,
) -> Path:
    """A real `graph.v4.json` always has `offsets`/`neighbors` alongside
    `node_ids` -- defaults to a valid, edge-free CSR (every node's own
    offset range is empty) rather than omitting them, so this fixture
    matches the real schema even when a test doesn't care about bridge_span."""
    path.write_text(
        json.dumps(
            {
                "node_ids": existing_node_ids,
                "offsets": offsets if offsets is not None else [0] * (len(existing_node_ids) + 1),
                "neighbors": neighbors if neighbors is not None else [],
            }
        )
    )
    return path


def test_scores_candidates_and_writes_a_local_only_artifact(tmp_path: Path) -> None:
    dataset = _write_onehop_dataset(tmp_path)
    masters_root = _write_masters_dataset(tmp_path)
    release_format_policy = _write_release_format_policy(tmp_path / "policy.json")
    exclusions = _write_exclusions(tmp_path / "exclusions.json", master_ids=[901])
    pathfinding_graph = _write_pathfinding_graph(
        tmp_path / "graph.v4.json", existing_node_ids=[100, -1]
    )
    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps(
            [
                {"master_id": 900, "artist_id": 100, "artist_name": "Alice"},
                {"master_id": 901, "artist_id": 400, "artist_name": "Dan"},
            ]
        )
    )
    editorial = tmp_path / "editorial.json"
    editorial.write_text(json.dumps({"master_ids": [900]}))
    output = tmp_path / "local" / "analysis" / "expansion" / "round-1" / "scored-candidates.json"

    exit_code = main(
        [
            "score-expansion-candidates",
            "--onehop-root",
            str(dataset),
            "--masters-root",
            str(masters_root),
            "--candidates",
            str(candidates),
            "--pathfinding-graph",
            str(pathfinding_graph),
            "--release-format-policy",
            str(release_format_policy),
            "--studio-album-exclusions",
            str(exclusions),
            "--editorial-master-ids",
            str(editorial),
            "--output",
            str(output),
            "--quiet",
        ]
    )
    assert exit_code == 0

    payload = json.loads(output.read_text())
    assert payload["candidate_count"] == 2
    assert payload["eligible_count"] == 1
    by_master = {row["master_id"]: row for row in payload["candidates"]}

    eligible = by_master[900]
    assert eligible["eligibility"] == "eligible"
    assert eligible["roster_size"] == 2
    assert eligible["overlap_existing"] == 1  # Alice (100) already a real graph node
    assert eligible["new_performers"] == 1  # Bob (200) is new
    assert eligible["editorial"] == 1

    ineligible = by_master[901]
    assert ineligible["eligibility"] == "curated_master_exclusion"
    assert ineligible["roster_size"] is None
    assert ineligible["editorial"] == 0


def test_refuses_to_write_outside_local(tmp_path: Path) -> None:
    dataset = _write_onehop_dataset(tmp_path)
    masters_root = _write_masters_dataset(tmp_path)
    release_format_policy = _write_release_format_policy(tmp_path / "policy.json")
    pathfinding_graph = _write_pathfinding_graph(tmp_path / "graph.v4.json", existing_node_ids=[])
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps([]))
    output = tmp_path / "apps" / "web" / "public" / "data" / "scored.json"

    with pytest.raises(ValueError, match="refuses to write outside local/"):
        main(
            [
                "score-expansion-candidates",
                "--onehop-root",
                str(dataset),
                "--masters-root",
                str(masters_root),
                "--candidates",
                str(candidates),
                "--pathfinding-graph",
                str(pathfinding_graph),
                "--release-format-policy",
                str(release_format_policy),
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


def test_existing_node_ids_ignores_negative_virtual_anchor_ids(tmp_path: Path) -> None:
    """A candidate's roster can never overlap a virtual album-anchor id (a
    real pathfinding_graph.v4.json's own negative node_ids) -- confirms the
    CLI filters them out before computing overlap_existing, not just that
    the underlying scorer would handle a clean set correctly."""
    dataset = _write_onehop_dataset(tmp_path)
    masters_root = _write_masters_dataset(tmp_path)
    release_format_policy = _write_release_format_policy(tmp_path / "policy.json")
    # -100 is a virtual album-anchor id -- if it leaked through un-filtered,
    # it could never match a real roster artist_id anyway, but this proves
    # the CLI's own filter runs rather than relying on that coincidence.
    pathfinding_graph = _write_pathfinding_graph(
        tmp_path / "graph.v4.json", existing_node_ids=[100, -100]
    )
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps([{"master_id": 900}]))
    output = tmp_path / "local" / "out.json"

    exit_code = main(
        [
            "score-expansion-candidates",
            "--onehop-root",
            str(dataset),
            "--masters-root",
            str(masters_root),
            "--candidates",
            str(candidates),
            "--pathfinding-graph",
            str(pathfinding_graph),
            "--release-format-policy",
            str(release_format_policy),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text())
    assert payload["candidates"][0]["overlap_existing"] == 1


def test_bridge_span_and_coverage_delta_wire_through_the_cli(tmp_path: Path) -> None:
    dataset = _write_onehop_dataset(tmp_path)
    masters_root = _write_masters_dataset(tmp_path)
    release_format_policy = _write_release_format_policy(tmp_path / "policy.json")
    # Alice (100, index 0) is connected to two distinct virtual album-anchor
    # nodes (-1, -2, ADR 0058); Bob (200, index 1) has no graph presence.
    pathfinding_graph = _write_pathfinding_graph(
        tmp_path / "graph.v4.json",
        existing_node_ids=[100, 200, -1, -2],
        offsets=[0, 2, 2, 2, 2],
        neighbors=[2, 3],
    )
    underrepresented = tmp_path / "underrepresented.json"
    # Master 900's real genres/styles/year (from _write_masters_dataset) are
    # [], [], 1995 -- decade "1990s" is the one real match here.
    underrepresented.write_text(
        json.dumps(
            [
                {"dimension": "decades", "bucket": "1990s", "count": 0},
                {"dimension": "genres", "bucket": "Jazz", "count": 1},
            ]
        )
    )
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps([{"master_id": 900}]))
    output = tmp_path / "local" / "out.json"

    exit_code = main(
        [
            "score-expansion-candidates",
            "--onehop-root",
            str(dataset),
            "--masters-root",
            str(masters_root),
            "--candidates",
            str(candidates),
            "--pathfinding-graph",
            str(pathfinding_graph),
            "--release-format-policy",
            str(release_format_policy),
            "--underrepresented-buckets",
            str(underrepresented),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    row = json.loads(output.read_text())["candidates"][0]
    assert row["bridge_span"] == 2
    assert row["coverage_delta"] == 1
