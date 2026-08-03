from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main


@pytest.fixture
def editorial_path(tmp_path: Path) -> Path:
    path = tmp_path / "editorial.json"
    path.write_text(json.dumps({"albums": [{"artist": "Alice", "title": "First Light"}]}))
    return path


@pytest.fixture
def candidates_path(tmp_path: Path, dataset_root: Path) -> Path:
    path = tmp_path / "candidates.json"
    exit_code = main(
        [
            "rank-album-candidates",
            "--dataset",
            str(dataset_root),
            "--output",
            str(path),
        ]
    )
    assert exit_code == 0
    return path


def test_rank_exploration_tier_refuses_output_outside_local(
    dataset_root: Path, editorial_path: Path, candidates_path: Path, tmp_path: Path
) -> None:
    outside_output = tmp_path / "apps" / "web" / "public" / "data" / "tier.json"
    with pytest.raises(ValueError, match="local/"):
        main(
            [
                "rank-exploration-tier",
                "--onehop-root",
                str(dataset_root),
                "--editorial-albums",
                str(editorial_path),
                "--candidates",
                str(candidates_path),
                "--target-count",
                "500",
                "--output",
                str(outside_output),
            ]
        )
    assert not outside_output.exists()


def test_rank_exploration_tier_writes_under_local_with_exploration_corpus_version(
    dataset_root: Path,
    editorial_path: Path,
    candidates_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "local" / "analysis" / "exploration-tiers" / "tier-500.json"
    exit_code = main(
        [
            "rank-exploration-tier",
            "--onehop-root",
            str(dataset_root),
            "--editorial-albums",
            str(editorial_path),
            "--candidates",
            str(candidates_path),
            "--target-count",
            "500",
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["exploration_corpus_version"].startswith("explore-v1-")

    tier = json.loads(output_path.read_text())
    assert "catalog_version" not in tier
    assert tier["exploration_corpus_version"].startswith("explore-v1-")
    assert tier["target_count"] == 500
    assert "MEASUREMENT ONLY" in tier["note"]
