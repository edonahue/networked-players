"""Fixture test for Slice E's `research.graph-metrics` workload
(`platform_jobs.py`): the same DJ-compilation-shaped correctness fixture
`test_graph_bench.py` uses for `load_edges`, run through the actual
platform-dispatched handler rather than calling `load_edges` directly."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from networked_players_catalog.discogs.parquet import SCHEMAS
from networked_players_platform.models import CapabilityRequirement, RunRequest
from networked_players_platform.workloads import discover_workloads
from networked_players_research.platform_jobs import (
    _degree_distribution_handler,
    graph_metrics_workload,
)

COMMIT = "a" * 40


def _write_corpus(root: Path) -> None:
    (root / "table=releases").mkdir(parents=True)
    (root / "table=credits").mkdir(parents=True)
    release_row = {
        "snapshot_date": "20260601",
        "release_id": 1,
        "status": "Accepted",
        "title": "A Real Album",
        "country": None,
        "released": "1995",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": "https://example.invalid/release/1",
    }
    credit_rows = []
    for artist_id in (100, 200):
        # A billed release_artist credit plus a same-track_index track_artist
        # credit -- credit_edges_sql's `same_recording` rule requires one
        # endpoint to be a billed artist on the release, not just any two
        # credits sharing a track_index (see its own docstring).
        credit_rows.append(
            {
                "snapshot_date": "20260601",
                "release_id": 1,
                "track_index": None,
                "track_path": None,
                "track_position": None,
                "track_title": None,
                "credit_scope": "release_artist",
                "artist_id": artist_id,
                "name": f"Artist {artist_id}",
                "anv": None,
                "join_text": None,
                "role_text": None,
                "credited_tracks_text": None,
                "is_linked": True,
                "playable_identity": True,
            }
        )
        credit_rows.append(
            {
                "snapshot_date": "20260601",
                "release_id": 1,
                "track_index": 0,
                "track_path": "0",
                "track_position": "1",
                "track_title": "Track 1",
                "credit_scope": "track_artist",
                "artist_id": artist_id,
                "name": f"Artist {artist_id}",
                "anv": None,
                "join_text": None,
                "role_text": None,
                "credited_tracks_text": None,
                "is_linked": True,
                "playable_identity": True,
            }
        )
    pq.write_table(
        pa.Table.from_pylist([release_row], schema=SCHEMAS["releases"]),
        root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(credit_rows, schema=SCHEMAS["credits"]),
        root / "table=credits" / "part-00000.parquet",
    )


def test_installed_graph_metrics_workload_is_discoverable() -> None:
    workload = discover_workloads()["research.graph-metrics"]
    assert workload.spec.version == "1"
    assert workload.spec.capabilities.architectures == ("x86_64",)
    assert workload.spec.capabilities.tags == ("graph", "x86-heavy")
    assert workload.spec.capabilities.min_memory_mb == 1024


def test_degree_distribution_handler_computes_a_real_metric(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    _write_corpus(input_dir)
    output_dir = tmp_path / "output"

    request = RunRequest(
        schema_version=1,
        run_id="graph-metrics-001",
        workload_id="research.graph-metrics",
        workload_version="1",
        submitted_at="2026-08-04T00:00:00+00:00",
        runtime_commit=COMMIT,
        timeout_seconds=600,
        max_retries=0,
        capabilities=CapabilityRequirement(),
        inputs=(),
        expected_outputs=("degree-distribution",),
        parameters={},
    )

    outputs = _degree_distribution_handler(request, input_dir, output_dir)

    report = json.loads((output_dir / "degree-distribution.json").read_text())
    assert report["node_count"] == 2
    assert report["edge_count"] == 1
    assert report["max_degree"] == 1
    assert outputs[0].name == "degree-distribution"


def test_graph_metrics_workload_spec_matches_the_registered_handler() -> None:
    assert graph_metrics_workload().handler is _degree_distribution_handler
