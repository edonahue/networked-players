from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.challenge import build_challenge_v2
from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.verify import VerifyDatasetError, verify_challenge_evidence

ALBUMS = [
    {"artist": "Alice", "title": "First Light"},
    {"artist": "Cara", "title": "Third Wave"},
    {"artist": "Eve", "title": "Sixth Sense"},
]


def _build_artifact(dataset_root: Path) -> dict:
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )
    return artifact


def test_verify_passes_on_a_genuine_artifact(dataset_root: Path) -> None:
    artifact = _build_artifact(dataset_root)

    report = verify_challenge_evidence(artifact, dataset_root)

    assert report["failures"] == []
    assert report["paths_checked"] == len(artifact["paths"])
    assert report["hops_verified"] > 0
    assert report["evidence_rows_checked"] > 0


def test_verify_reports_tampered_evidence_row(dataset_root: Path) -> None:
    artifact = _build_artifact(dataset_root)
    artifact["releases"][0]["credits"][0]["role_text"] = "Definitely Not The Real Role"

    report = verify_challenge_evidence(artifact, dataset_root)

    assert report["failures"]
    assert any("not found verbatim" in f for f in report["failures"])


def test_verify_reports_missing_release(dataset_root: Path) -> None:
    artifact = _build_artifact(dataset_root)
    artifact["releases"] = [r for r in artifact["releases"] if r["release_id"] != 1]

    report = verify_challenge_evidence(artifact, dataset_root)

    assert any("not published" in f for f in report["failures"])


def test_verify_reports_unlinked_endpoint(dataset_root: Path) -> None:
    artifact = _build_artifact(dataset_root)
    # Point a hop's endpoint at an artist with no credit on that release.
    artifact["paths"][0]["hops"][0]["artist_b_id"] = 999_999

    report = verify_challenge_evidence(artifact, dataset_root)

    assert any("no playable credit" in f for f in report["failures"])


def test_verify_respects_path_ids_filter(dataset_root: Path) -> None:
    artifact = _build_artifact(dataset_root)
    first_path_id = artifact["paths"][0]["id"]

    report = verify_challenge_evidence(artifact, dataset_root, path_ids=[first_path_id])

    assert report["paths_checked"] == 1


def test_verify_raises_clear_error_for_missing_dataset(tmp_path: Path) -> None:
    artifact = {"releases": [], "paths": []}
    with pytest.raises(VerifyDatasetError, match=r"no manifest\.json"):
        verify_challenge_evidence(artifact, tmp_path / "does-not-exist")
