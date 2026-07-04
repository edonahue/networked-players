"""Cross-checks the self-contained Pi job body against the reference
implementation on identical inputs, to catch the two drifting apart --
infra/ansible/files/verify_challenge_job.py is a hand-maintained mirror of
networked_players_graph_core.verify (see that job body's own header comment)
because a Pi's lean venv can't import graph-core.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from conftest import FIXTURE_CREDITS, FIXTURE_RELEASES, write_synthetic_dataset
from networked_players_graph_core.challenge import build_challenge_v2
from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.verify import verify_challenge_evidence

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3] / "infra" / "ansible" / "files" / "verify_challenge_job.py"
)
ALBUMS = [
    {"artist": "Alice", "title": "First Light"},
    {"artist": "Cara", "title": "Third Wave"},
    {"artist": "Eve", "title": "Sixth Sense"},
]


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("verify_challenge_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_challenge_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["verify_challenge_job"]


@pytest.fixture
def cached_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A validated ADR-0025-shaped cache plus a matching challenge artifact on disk."""
    cache_root = tmp_path / "cache"
    dataset_root = cache_root / "discogs-onehop" / "snapshot=20260601"
    write_synthetic_dataset(
        dataset_root, release_rows=FIXTURE_RELEASES, credit_rows=FIXTURE_CREDITS
    )
    (dataset_root / ".verified.json").write_text(json.dumps({"verified_at": "test"}))

    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )
    artifact_path = tmp_path / "challenge.v2.json"
    artifact_path.write_text(json.dumps(artifact))

    monkeypatch.setenv("CATALOG_DATA_DIR", str(cache_root))
    return artifact, artifact_path, dataset_root


def test_job_body_matches_reference_on_a_clean_artifact(job_body_module, cached_artifact) -> None:
    artifact, artifact_path, dataset_root = cached_artifact
    path_ids = [p["id"] for p in artifact["paths"]]

    reference = verify_challenge_evidence(artifact, dataset_root, path_ids=path_ids)
    job_result = job_body_module.verify_shard(str(artifact_path), path_ids)

    assert job_result == reference


def test_job_body_matches_reference_on_tampered_evidence(job_body_module, cached_artifact) -> None:
    artifact, artifact_path, dataset_root = cached_artifact
    artifact["releases"][0]["credits"][0]["role_text"] = "Tampered"
    artifact_path.write_text(json.dumps(artifact))
    path_ids = [p["id"] for p in artifact["paths"]]

    reference = verify_challenge_evidence(artifact, dataset_root, path_ids=path_ids)
    job_result = job_body_module.verify_shard(str(artifact_path), path_ids)

    assert job_result == reference
    assert reference["failures"]
