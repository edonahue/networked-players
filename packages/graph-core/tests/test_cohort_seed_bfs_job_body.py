"""Cross-checks the self-contained fleet-dispatch job body against the
reference implementation on identical inputs, to catch the two drifting
apart -- infra/ansible/files/cohort_seed_bfs_job.py is a hand-maintained
mirror of networked_players_graph_core.cohort_connectivity._bfs_from_seed
(see ADR 0032 and that job body's own header comment) because a Pi's lean
venv can't import graph-core.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from conftest import FIXTURE_CREDITS, FIXTURE_RELEASES, write_synthetic_dataset
from networked_players_graph_core.cohort_connectivity import _bfs_from_seed
from networked_players_graph_core.graph import CreditGraph

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3] / "infra" / "ansible" / "files" / "cohort_seed_bfs_job.py"
)
SEED_ARTIST_IDS = [100, 200, 300, 400, 500]


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("cohort_seed_bfs_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cohort_seed_bfs_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["cohort_seed_bfs_job"]


@pytest.fixture
def cached_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A validated ADR-0025-shaped one-hop cache on disk."""
    cache_root = tmp_path / "cache"
    dataset_root = cache_root / "discogs-onehop" / "snapshot=20260601"
    write_synthetic_dataset(
        dataset_root, release_rows=FIXTURE_RELEASES, credit_rows=FIXTURE_CREDITS
    )
    (dataset_root / ".verified.json").write_text(json.dumps({"verified_at": "test"}))
    monkeypatch.setenv("CATALOG_DATA_DIR", str(cache_root))
    return dataset_root


def _reference_results(
    dataset_root: Path, seed_artist_ids: list[int], *, max_hops: int, max_frontier_expansion
) -> dict[str, dict]:
    neighbor_cache: dict[int, dict[int, tuple[int, ...]]] = {}
    results: dict[str, dict] = {}
    with CreditGraph.open(dataset_root) as graph:
        for seed_artist_id in seed_artist_ids:
            parent, capped = _bfs_from_seed(
                graph,
                seed_artist_id,
                max_hops=max_hops,
                max_frontier_expansion=max_frontier_expansion,
                neighbor_cache=neighbor_cache,
                deadline=None,
            )
            results[str(seed_artist_id)] = {
                "status": "ok",
                "parent": {
                    (artist_id, parent_id, release_id)
                    for artist_id, (parent_id, release_id) in parent.items()
                },
                "capped": set(capped),
            }
    return results


def test_job_body_matches_reference_on_a_clean_chunk(job_body_module, cached_dataset) -> None:
    job_result = job_body_module.run_seed_bfs_chunk(
        SEED_ARTIST_IDS, 3, 300, "20260601", pair_timeout_seconds=None
    )
    reference = _reference_results(
        cached_dataset, SEED_ARTIST_IDS, max_hops=3, max_frontier_expansion=300
    )

    assert set(job_result.keys()) == set(reference.keys())
    for seed_key in reference:
        assert job_result[seed_key]["status"] == "ok"
        job_parent = {tuple(triple) for triple in job_result[seed_key]["parent"]}
        assert job_parent == reference[seed_key]["parent"]
        assert set(job_result[seed_key]["capped"]) == reference[seed_key]["capped"]


def test_job_body_matches_reference_with_a_tight_frontier_cap(
    job_body_module, cached_dataset
) -> None:
    """A tiny max_frontier_expansion should produce capped artists on both
    sides identically -- this is the branch that actually exercises the
    batched credit_row_counts/neighbors_batch queries with real exclusions."""
    job_result = job_body_module.run_seed_bfs_chunk(
        SEED_ARTIST_IDS, 3, 1, "20260601", pair_timeout_seconds=None
    )
    reference = _reference_results(
        cached_dataset, SEED_ARTIST_IDS, max_hops=3, max_frontier_expansion=1
    )

    for seed_key in reference:
        job_parent = {tuple(triple) for triple in job_result[seed_key]["parent"]}
        assert job_parent == reference[seed_key]["parent"]
        assert set(job_result[seed_key]["capped"]) == reference[seed_key]["capped"]
