"""Cross-checks the constrained-worker adapter against graph-core's public
`validate_record_routes_artifact` on identical inputs. Mirrors
test_connection_rounds_check_job_body.py exactly, adapted for Record Routes'
`record_routes_check_job.py` and its two-argument
`check_record_routes(universe_path, rounds_path)` entry point.

Comparison is behavioral (does the reference function raise vs. does the
mirror report invalid), not exact failure-string equality.
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
from networked_players_graph_core.record_routes import (
    RecordRoutesValidationError,
    validate_record_routes_artifact,
)

JOB_BODY_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "ansible"
    / "files"
    / "record_routes_check_job.py"
)

_SNAPSHOT_DATE = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


@pytest.fixture
def job_body_module():
    spec = importlib.util.spec_from_file_location("record_routes_check_job", JOB_BODY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_routes_check_job"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["record_routes_check_job"]


def _hop(release_id: int, a: int, b: int) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "artist_a_id": a,
        "artist_b_id": b,
        "role_a": "Guitar",
        "role_b": "Bass",
        "quality_flags": ["performer_credit", "same_recording"],
    }


def _route() -> dict[str, Any]:
    endpoints = sorted(("master-1", "master-2"))
    hop_part = "500:100:200"
    route_id = f"route-{stable_id_digest('rr', *endpoints, hop_part)}"
    return {
        "id": route_id,
        "kind": "one_hop",
        "difficulty": "medium",
        "from_album_id": "master-1",
        "to_album_id": "master-2",
        "from_artist_id": 100,
        "to_artist_id": 200,
        "hops": [_hop(500, 100, 200)],
        "distractors": [],
    }


def _album(album_id: str) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": int(album_id.split("-")[1]),
        "main_release_id": int(album_id.split("-")[1]),
        "title": album_id.title(),
        "artist_id": 100,
        "artist": "Act",
        "year": 1990,
    }


def _provenance(
    routes: list[dict[str, Any]],
    albums: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    artists: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {"albums": albums, "rounds": routes, "releases": releases, "artists": artists}
    return {
        "source": "Discogs monthly data dump (CC0), one-hop working set",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "snapshot_date": _SNAPSHOT_DATE,
        "generated_by": "networked-players-catalog build-record-routes 0.1.0",
        "graph_core_version": "0.1.0",
        "note": "Real path evidence.",
        "catalog_version": _CATALOG_VERSION,
        "artifact_version": (
            f"routes-artifact-v1-{_SNAPSHOT_DATE}-{content_hash(payload, length=12)}"
        ),
    }


def _pair() -> tuple[dict[str, Any], dict[str, Any]]:
    routes = [_route()]
    ids = sorted(r["id"] for r in routes)
    pool_version = f"routes-v1-{_SNAPSHOT_DATE}-{content_hash(ids, length=12)}"
    albums = [_album("master-1"), _album("master-2")]
    releases = [{"release_id": 500, "title": "Release 500"}]
    artists = [{"artist_id": 100, "name": "Artist 100"}, {"artist_id": 200, "name": "Artist 200"}]
    prov = _provenance(routes, albums, releases, artists)
    universe = {
        "schema_version": 1,
        "mode": "record_routes",
        "pool_version": pool_version,
        "provenance": prov,
        "counts": {"one_hop": 1, "two_hop": 0, "daily_eligible": 1},
        "albums": albums,
    }
    rounds = {
        "schema_version": 1,
        "mode": "record_routes",
        "pool_version": pool_version,
        "provenance": prov,
        "rounds": routes,
        "releases": releases,
        "artists": artists,
    }
    return universe, rounds


def _write(tmp_path: Path, name: str, artifact: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(artifact))
    return path


def test_clean_pair_matches(job_body_module, tmp_path: Path) -> None:
    universe, rounds = _pair()
    universe_path = _write(tmp_path, "routes-universe.v1.json", universe)
    rounds_path = _write(tmp_path, "routes-rounds.v1.json", rounds)

    validate_record_routes_artifact(universe, rounds)  # does not raise
    result = job_body_module.check_record_routes(str(universe_path), str(rounds_path))
    assert result == {"valid": True, "failures": []}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda u, r: r["rounds"][0].__setitem__("id", "round-000001"),
        lambda u, r: r.__setitem__("mode", "connection_guesser_one_hop"),
        lambda u, r: u["albums"][0].__setitem__("cover_image", {"uri": "x"}),
        lambda u, r: u.update(extra_top_level_key="nope"),
    ],
)
def test_broken_pair_matches(job_body_module, tmp_path: Path, mutate) -> None:
    universe, rounds = _pair()
    mutate(universe, rounds)
    universe_path = _write(tmp_path, "routes-universe.v1.json", universe)
    rounds_path = _write(tmp_path, "routes-rounds.v1.json", rounds)

    with pytest.raises(RecordRoutesValidationError):
        validate_record_routes_artifact(copy.deepcopy(universe), copy.deepcopy(rounds))
    result = job_body_module.check_record_routes(str(universe_path), str(rounds_path))
    assert result["valid"] is False
    assert result["failures"]
