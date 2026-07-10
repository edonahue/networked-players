"""Cross-checks the constrained-worker adapter against graph-core's public
validation wrappers on identical inputs. Both delegate to the independently
installable `networked_players_contracts` package; this test protects the adapter's
file-I/O and serializable-result behavior without maintaining validator logic twice.

Comparison is behavioral (does the reference function raise vs. does the
mirror report invalid), not exact failure-string equality: the reference
functions raise once with a semicolon-joined message after collecting
structural failures (plus a separate, immediate raise for the first
forbidden substring/phrase found), while the mirror always returns a
complete failures list without raising. Matching that raise/no-raise
classification is the meaningful drift signal; incidental differences in
message formatting are not.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.cohort_connectivity import (
    CohortConnectivityError,
    validate_connectivity,
)
from networked_players_graph_core.cohort_promote import (
    CohortPromoteError,
    validate_playable_cohort,
)

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "ansible"
    / "files"
    / "cohort_artifact_check_job.py"
)

SOURCE = {
    "source_url": "https://example.invalid/fake-digs-post",
    "page_title": "Fake Digs Post",
    "saved_at": "2026-07-05",
    "operator_note": "",
}


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("cohort_artifact_check_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cohort_artifact_check_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["cohort_artifact_check_job"]


def _valid_connectivity() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": SOURCE,
        "scorer_version": 2,
        "generated_at": "2026-07-05T00:00:00+00:00",
        "dataset_snapshot_date": "20260601",
        "max_hops": 3,
        "pairs": [
            {
                "album_a_id": "release-1",
                "album_b_id": "release-2",
                "artist_a_id": 100,
                "artist_b_id": 300,
                "status": "found",
                "hop_count": 1,
                "difficulty": "easy",
                "hops": [
                    {
                        "release_id": 1,
                        "artist_a_id": 100,
                        "artist_b_id": 300,
                        "quality_flags": ["co_billed_release_artists"],
                    }
                ],
                "warnings": [],
                "skip_reason": None,
            }
        ],
        "unresolved": [],
    }


def _valid_playable_cohort() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cohort_id": "test-cohort",
        "attribution_label": "Fake Digs Post",
        "source_url": SOURCE["source_url"],
        "generated_from_scorer_version": 2,
        "reviewed_at": "2026-07-05T12:00:00+00:00",
        "review_note": None,
        "albums": [
            {
                "id": "release-1",
                "artist_id": 100,
                "artist": "Alice",
                "title": "First Light",
                "year": 1993,
            },
            {
                "id": "release-2",
                "artist_id": 300,
                "artist": "Cara",
                "title": "Third Wave",
                "year": 1995,
            },
        ],
        "pairs": [
            {
                "album_a_id": "release-1",
                "album_b_id": "release-2",
                "artist_a_id": 100,
                "artist_b_id": 300,
                "difficulty": "easy",
                "hop_count": 1,
                "hops": [
                    {
                        "release_id": 1,
                        "artist_a_id": 100,
                        "artist_b_id": 300,
                        "quality_flags": ["co_billed_release_artists"],
                    }
                ],
                "warnings": [],
            }
        ],
    }


def _write(tmp_path: Path, name: str, artifact: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(artifact))
    return path


# --- check_connectivity vs validate_connectivity ---


def test_connectivity_clean_artifact_matches(job_body_module, tmp_path: Path) -> None:
    artifact = _valid_connectivity()
    path = _write(tmp_path, "connectivity.json", artifact)

    validate_connectivity(artifact)  # does not raise
    result = job_body_module.check_connectivity(str(path))
    assert result == {"valid": True, "failures": []}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(extra_top_level_key="nope"),
        lambda a: a["pairs"][0].__setitem__("status", "not-a-real-status"),
        lambda a: a["pairs"][0]["hops"][0].__setitem__("quality_flags", ["placeholder_artist_hop"]),
        lambda a: a["pairs"][0].__setitem__(
            "warnings", [f"see local/analysis/{a['pairs'][0]['album_a_id']}"]
        ),
    ],
)
def test_connectivity_broken_artifact_matches(job_body_module, tmp_path: Path, mutate) -> None:
    artifact = _valid_connectivity()
    mutate(artifact)
    path = _write(tmp_path, "connectivity.json", artifact)

    with pytest.raises(CohortConnectivityError):
        validate_connectivity(artifact)
    result = job_body_module.check_connectivity(str(path))
    assert result["valid"] is False
    assert result["failures"]


# --- check_playable_cohort vs validate_playable_cohort ---


def test_playable_cohort_clean_artifact_matches(job_body_module, tmp_path: Path) -> None:
    artifact = _valid_playable_cohort()
    path = _write(tmp_path, "playable-cohort-v1.json", artifact)

    validate_playable_cohort(artifact)  # does not raise
    result = job_body_module.check_playable_cohort(str(path))
    assert result == {"valid": True, "failures": []}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(extra_top_level_key="nope"),
        lambda a: a["pairs"][0].__setitem__("difficulty", "not-a-real-difficulty"),
        lambda a: a["pairs"][0]["hops"][0].__setitem__("quality_flags", ["placeholder_artist_hop"]),
        lambda a: a.__setitem__("review_note", "these two artists worked with each other"),
    ],
)
def test_playable_cohort_broken_artifact_matches(job_body_module, tmp_path: Path, mutate) -> None:
    artifact = _valid_playable_cohort()
    mutate(artifact)
    path = _write(tmp_path, "playable-cohort-v1.json", artifact)

    with pytest.raises(CohortPromoteError):
        validate_playable_cohort(artifact)
    result = job_body_module.check_playable_cohort(str(path))
    assert result["valid"] is False
    assert result["failures"]
