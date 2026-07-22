"""Cross-checks the constrained-worker adapter against graph-core's public
`validate_connection_rounds_artifact` on identical inputs. Mirrors
test_rounds_check_job_body.py/test_cohort_check_job_body.py exactly, adapted
for the Connection Guesser's `connection_rounds_check_job.py` and its
two-argument `check_connection_rounds(universe_path, rounds_path)` entry
point. This is the drift-prevention test ADR 0043's slice-8 addendum notes
was missing since Finding 8 first added `connection_rounds_check_job.py`.

Comparison is behavioral (does the reference function raise vs. does the
mirror report invalid), not exact failure-string equality: the reference
raises once with a semicolon-joined message after collecting structural
failures, while the mirror always returns a complete failures list without
raising.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from networked_players_contracts.canonical import content_hash, stable_id_digest
from networked_players_contracts.connection_rounds import round_content_fingerprint
from networked_players_graph_core.connection_rounds import (
    ConnectionRoundsValidationError,
    validate_connection_rounds_artifact,
)

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "ansible"
    / "files"
    / "connection_rounds_check_job.py"
)

_SNAPSHOT_DATE = "20260601"
_ROUND_ID = f"conn-{stable_id_digest('1h', 'album-a', 'album-c', '700')}"


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("connection_rounds_check_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["connection_rounds_check_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["connection_rounds_check_job"]


def _round() -> dict[str, Any]:
    return {
        "id": _ROUND_ID,
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": "hard",
        "endpoints": [
            {
                "id": "album-a",
                "title": "First Light",
                "year": 1995,
                "act": "Alice",
                "label": None,
                "art": None,
            },
            {
                "id": "album-c",
                "title": "Third Wave",
                "year": 1996,
                "act": "Cara",
                "label": None,
                "art": None,
            },
        ],
        "answer_set": [{"id": 700, "name": "Xavier", "role_category": "guitar"}],
        "distractors": [{"id": 750, "name": "Walt", "role_category": "drums"}],
        "clues": [
            {
                "kind": "eliminate",
                "text": "One name struck from the tray.",
                "eliminate_ids": [750],
            }
        ],
        "evidence": [
            {
                "release_ref": "album-a",
                "release_title": "First Light",
                "contributor_id": 700,
                "credited_as": "Xavier",
                "role_text": "Guitar",
                "credit_scope": "release_credit",
            },
            {
                "release_ref": "album-c",
                "release_title": "Third Wave",
                "contributor_id": 700,
                "credited_as": "Xavier",
                "role_text": "Guitar",
                "credit_scope": "release_credit",
            },
        ],
        "provenance_note": "Real records: derived from the Discogs monthly data dump (CC0).",
    }


def _artifact_version(rounds: list[dict[str, Any]]) -> str:
    fingerprints = [round_content_fingerprint(r) for r in rounds]
    digest = content_hash(fingerprints, length=12)
    return f"connection-artifact-v1-{_SNAPSHOT_DATE}-{digest}"


_PROVENANCE = {
    "source": "Discogs monthly data dump (CC0), one-hop working set",
    "license": "See docs/DATA_AND_RIGHTS.md.",
    "snapshot_date": _SNAPSHOT_DATE,
    "generated_by": "networked-players-catalog build-connection-rounds 0.1.0",
    "catalog_version": "catalog-v1-20260601-abc123abc123",
    "pool_version": "connection-v1-20260601-def456def456",
    "artifact_version": _artifact_version([_round()]),
    "note": "Real records, not synthetic.",
}


def _valid_universe() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": dict(_PROVENANCE),
        "albums": [
            {
                "id": "album-a",
                "title": "First Light",
                "act": "Alice",
                "act_id": 100,
                "year": 1995,
                "label": None,
                "art": None,
            },
            {
                "id": "album-c",
                "title": "Third Wave",
                "act": "Cara",
                "act_id": 300,
                "year": 1996,
                "label": None,
                "art": None,
            },
        ],
        "contributors": [
            {"id": 700, "name": "Xavier", "role_category": "guitar"},
            {"id": 750, "name": "Walt", "role_category": "drums"},
        ],
        "releases": [
            {
                "id": "album-a",
                "album_id": "album-a",
                "title": "First Light",
                "year": 1995,
                "catalog_stamp": "DISCOGS-1",
            },
            {
                "id": "album-c",
                "album_id": "album-c",
                "title": "Third Wave",
                "year": 1996,
                "catalog_stamp": "DISCOGS-2",
            },
        ],
        "credits": [
            {
                "release_id": "album-a",
                "contributor_id": 700,
                "role_text": "Guitar",
                "role_category": "guitar",
                "credit_scope": "release_credit",
            },
            {
                "release_id": "album-c",
                "contributor_id": 700,
                "role_text": "Guitar",
                "role_category": "guitar",
                "credit_scope": "release_credit",
            },
        ],
    }


def _valid_rounds() -> dict[str, Any]:
    return {"schema_version": 1, "provenance": dict(_PROVENANCE), "rounds": [_round()]}


def _write(tmp_path: Path, name: str, artifact: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(artifact))
    return path


def test_clean_pair_matches(job_body_module, tmp_path: Path) -> None:
    universe = _valid_universe()
    rounds = _valid_rounds()
    universe_path = _write(tmp_path, "connection-universe.v1.json", universe)
    rounds_path = _write(tmp_path, "connection-rounds.v1.json", rounds)

    validate_connection_rounds_artifact(universe, rounds)  # does not raise
    result = job_body_module.check_connection_rounds(str(universe_path), str(rounds_path))
    assert result == {"valid": True, "failures": []}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda u, r: r["rounds"][0].__setitem__("difficulty", "not-a-real-difficulty"),
        lambda u, r: r["rounds"][0]["endpoints"][0].__setitem__(
            "art", {"kind": "hotlink", "uri150": "x", "uri": "y"}
        ),
        lambda u, r: r["rounds"][0].__setitem__("pool", "synthetic"),
        lambda u, r: u.update(extra_top_level_key="nope"),
    ],
)
def test_broken_pair_matches(job_body_module, tmp_path: Path, mutate) -> None:
    universe = _valid_universe()
    rounds = _valid_rounds()
    mutate(universe, rounds)
    universe_path = _write(tmp_path, "connection-universe.v1.json", universe)
    rounds_path = _write(tmp_path, "connection-rounds.v1.json", rounds)

    with pytest.raises(ConnectionRoundsValidationError):
        validate_connection_rounds_artifact(copy.deepcopy(universe), copy.deepcopy(rounds))
    result = job_body_module.check_connection_rounds(str(universe_path), str(rounds_path))
    assert result["valid"] is False
    assert result["failures"]
