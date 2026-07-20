"""Cross-checks the constrained-worker adapter against graph-core's public
`validate_rounds_artifact` on identical inputs. Mirrors
test_cohort_check_job_body.py exactly, adapted for the rounds contract's
two-file (universe.v1/rounds.v1) shape and `rounds_check_job.py`'s
two-argument `check_rounds(universe_path, rounds_path)` entry point.

Comparison is behavioral (does the reference function raise vs. does the
mirror report invalid), not exact failure-string equality: the reference
raises once with a semicolon-joined message after collecting structural
failures (plus a separate, immediate raise for the first forbidden
substring/phrase found), while the mirror always returns a complete
failures list without raising.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.rounds import RoundsValidationError, validate_rounds_artifact

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3] / "infra" / "ansible" / "files" / "rounds_check_job.py"
)

PROVENANCE = {
    "source": "Discogs monthly data dump",
    "license": "https://discogs-data-dumps.s3.us-west-2.amazonaws.com/LICENSE.txt",
    "snapshot_date": "20260601",
    "generated_by": "build-rounds-from-dump",
    "graph_core_version": "0.1.0",
}


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("rounds_check_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rounds_check_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["rounds_check_job"]


def _valid_universe() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pool_version": "v1",
        "provenance": dict(PROVENANCE),
        "counts": {"albums": 1},
        "albums": [
            {
                "id": "release-1",
                "master_id": None,
                "main_release_id": None,
                "title": "First Light",
                "artist_id": 100,
                "artist": "Alice",
                "year": 1993,
                "cover_image": None,
            }
        ],
    }


def _valid_rounds() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pool_version": "v1",
        "provenance": dict(PROVENANCE),
        "rounds": [
            {
                "id": "round-000001",
                "kind": "one_hop",
                "difficulty": "easy",
                "from_album_id": "release-1",
                "to_album_id": "release-1",
                "from_artist_id": 100,
                "to_artist_id": 100,
                "hops": [
                    {
                        "release_id": 1,
                        "artist_a_id": 100,
                        "artist_b_id": 100,
                        "role_a": "Vocals",
                        "role_b": "Vocals",
                        "quality_flags": ["co_billed_release_artists", "same_recording"],
                    }
                ],
                "distractors": [],
            }
        ],
        "releases": [
            {
                "snapshot_date": "20260601",
                "release_id": 1,
                "status": "Accepted",
                "title": "First Light",
                "country": "US",
                "released": "1993",
                "master_id": None,
                "master_is_main_release": None,
                "data_quality": "Correct",
                "source_url": "https://www.discogs.com/release/1",
                "credits": [],
            }
        ],
        "artists": [{"artist_id": 100, "name": "Alice"}],
    }


def _write(tmp_path: Path, name: str, artifact: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(artifact))
    return path


def test_clean_pair_matches(job_body_module, tmp_path: Path) -> None:
    universe = _valid_universe()
    rounds = _valid_rounds()
    universe_path = _write(tmp_path, "universe.v1.json", universe)
    rounds_path = _write(tmp_path, "rounds.v1.json", rounds)

    validate_rounds_artifact(universe, rounds)  # does not raise
    result = job_body_module.check_rounds(str(universe_path), str(rounds_path))
    assert result == {"valid": True, "failures": []}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda u, r: r["rounds"][0].__setitem__("difficulty", "not-a-real-difficulty"),
        lambda u, r: r["rounds"][0]["hops"][0].__setitem__("role_a", ""),
        lambda u, r: r["rounds"][0].__setitem__("to_album_id", "release-does-not-exist"),
        lambda u, r: u.update(extra_top_level_key="nope"),
    ],
)
def test_broken_pair_matches(job_body_module, tmp_path: Path, mutate) -> None:
    universe = _valid_universe()
    rounds = _valid_rounds()
    mutate(universe, rounds)
    universe_path = _write(tmp_path, "universe.v1.json", universe)
    rounds_path = _write(tmp_path, "rounds.v1.json", rounds)

    with pytest.raises(RoundsValidationError):
        validate_rounds_artifact(copy.deepcopy(universe), copy.deepcopy(rounds))
    result = job_body_module.check_rounds(str(universe_path), str(rounds_path))
    assert result["valid"] is False
    assert result["failures"]
