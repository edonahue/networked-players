"""CLI wiring for `validate-public-artifacts` (the cross-artifact publication
gate). Full validation coverage for each individual contract already lives
in `packages/contracts/tests/test_public_artifacts_contracts.py` and each
artifact's own test suite -- this file only proves the CLI reads the right
files from the right flags and reports exit codes correctly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from networked_players_catalog.cli import main
from networked_players_contracts.album_art import album_art_version
from networked_players_contracts.canonical import content_hash, stable_id_digest
from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.connection_rounds import round_content_fingerprint

_SNAPSHOT = "20260601"
_CATALOG_VERSION_STR = "catalog-v1-20260601-abc123abc123"


def _catalog_album(album_id: str, *, artist_id: int, main_release_id: int) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": None,
        "main_release_id": main_release_id,
        "title": album_id.title(),
        "artist_id": artist_id,
        "artist": "Alice",
        "year": 1995,
    }


def _catalog() -> dict[str, Any]:
    albums = [_catalog_album("master-1", artist_id=100, main_release_id=1)]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT),
        "snapshot_date": _SNAPSHOT,
        "generated_by": "test",
        "albums": albums,
    }


def _album_art(catalog: dict[str, Any]) -> dict[str, Any]:
    entries = [
        {
            "album_id": "master-1",
            "main_release_id": 1,
            "uri150": "https://i.discogs.com/a/150.jpg",
            "uri": "https://i.discogs.com/a/full.jpg",
            "width": 600,
            "height": 600,
        }
    ]
    return {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "art_version": album_art_version(entries, _SNAPSHOT),
        "generated_at": "2026-07-22T00:00:00+00:00",
        "source": "Discogs API /releases/{id} images",
        "license": "presentational only",
        "albums": entries,
    }


_CONNECTION_ROUND_ID = f"conn-{stable_id_digest('1h', 'album-a', 'album-c', '700')}"


def _connection_round() -> dict[str, Any]:
    return {
        "id": _CONNECTION_ROUND_ID,
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
        "distractors": [],
        "clues": [],
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


def _connection_artifact_version(rounds: list[dict[str, Any]]) -> str:
    fingerprints = [round_content_fingerprint(r) for r in rounds]
    return f"connection-artifact-v1-{_SNAPSHOT}-{content_hash(fingerprints, length=12)}"


_CONNECTION_PROVENANCE = {
    "source": "Discogs monthly data dump (CC0), one-hop working set",
    "license": "See docs/DATA_AND_RIGHTS.md.",
    "snapshot_date": _SNAPSHOT,
    "generated_by": "test",
    "catalog_version": _CATALOG_VERSION_STR,
    "pool_version": "connection-v1-20260601-def456def456",
    "artifact_version": _connection_artifact_version([_connection_round()]),
    "note": "Real records, not synthetic.",
}


def _connection_universe() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": dict(_CONNECTION_PROVENANCE),
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
        "contributors": [{"id": 700, "name": "Xavier", "role_category": "guitar"}],
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


def _connection_rounds() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": dict(_CONNECTION_PROVENANCE),
        "rounds": [_connection_round()],
    }


def _daily_manifest() -> dict[str, Any]:
    round_json = _connection_round()
    return {
        "schema_version": 1,
        "mode": "connection_guesser_one_hop",
        "catalog_version": _CATALOG_VERSION_STR,
        "pool_version": _CONNECTION_PROVENANCE["pool_version"],
        "artifact_version": _CONNECTION_PROVENANCE["artifact_version"],
        "generated_at": "2026-07-22T00:00:00+00:00",
        "start_date": "2026-07-22",
        "schedule": [
            {
                "date": "2026-07-22",
                "round_id": round_json["id"],
                "round_fingerprint": round_content_fingerprint(round_json),
            }
        ],
    }


def _route_hop(release_id: int, a: int, b: int) -> dict[str, Any]:
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
    route_id = f"route-{stable_id_digest('rr', *endpoints, '500:100:200')}"
    return {
        "id": route_id,
        "kind": "one_hop",
        "difficulty": "medium",
        "from_album_id": "master-1",
        "to_album_id": "master-2",
        "from_artist_id": 100,
        "to_artist_id": 200,
        "hops": [_route_hop(500, 100, 200)],
        "distractors": [],
    }


def _routes_releases_and_artists(routes: list[dict[str, Any]]) -> tuple[list, list]:
    """Minimal `rounds.releases[]`/`rounds.artists[]` entries covering every
    hop reference in `routes` -- record_routes_failures checks every hop's
    release_id/artist_a_id/artist_b_id resolve against these."""
    release_ids: set[int] = set()
    artist_ids: set[int] = set()
    for route in routes:
        for hop in route["hops"]:
            release_ids.add(hop["release_id"])
            artist_ids.add(hop["artist_a_id"])
            artist_ids.add(hop["artist_b_id"])
    releases = [{"release_id": rid, "title": f"Release {rid}"} for rid in sorted(release_ids)]
    artists = [{"artist_id": aid, "name": f"Artist {aid}"} for aid in sorted(artist_ids)]
    return releases, artists


def _routes_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    routes = [_route()]
    albums = [
        _catalog_album("master-1", artist_id=100, main_release_id=1),
        _catalog_album("master-2", artist_id=200, main_release_id=2),
    ]
    releases, artists = _routes_releases_and_artists(routes)
    pool_version = (
        f"routes-v1-{_SNAPSHOT}-{content_hash(sorted(r['id'] for r in routes), length=12)}"
    )
    payload = {"albums": albums, "rounds": routes, "releases": releases, "artists": artists}
    prov = {
        "source": "Discogs monthly data dump (CC0), one-hop working set",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "snapshot_date": _SNAPSHOT,
        "generated_by": "test",
        "graph_core_version": "0.1.0",
        "note": "Real path evidence.",
        "catalog_version": _CATALOG_VERSION_STR,
        "artifact_version": f"routes-artifact-v1-{_SNAPSHOT}-{content_hash(payload, length=12)}",
    }
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


def _challenge_release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
        "credits": [],
    }


def _challenge(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "provenance": {
            "source": "Discogs monthly data dump (CC0), one-hop working set",
            "license": "Derived from the Discogs monthly CC0 data dumps. See "
            "docs/DATA_AND_RIGHTS.md.",
            "snapshot_date": _SNAPSHOT,
            "generated_by": "test",
            "graph_core_version": "0.1.0",
            "catalog_version": catalog["catalog_version"],
            "note": "Derived from a bounded one-hop working set.",
        },
        "albums": [_catalog_album("master-1", artist_id=100, main_release_id=1)],
        "artists": [{"artist_id": 100, "name": "Alice"}],
        "paths": [],
        "releases": [_challenge_release(1, "Alpha's Album")],
    }


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload))
    return path


def _write_all(tmp_path: Path) -> dict[str, Path]:
    catalog = _catalog()
    routes_universe, routes_rounds = _routes_pair()
    return {
        "catalog": _write(tmp_path / "albums.v1.json", catalog),
        "album_art": _write(tmp_path / "album-art.v1.json", _album_art(catalog)),
        "connection_universe": _write(
            tmp_path / "connection-universe.v1.json", _connection_universe()
        ),
        "connection_rounds": _write(tmp_path / "connection-rounds.v1.json", _connection_rounds()),
        "daily_manifest": _write(tmp_path / "daily-manifest.v1.json", _daily_manifest()),
        "routes_universe": _write(tmp_path / "routes-universe.v1.json", routes_universe),
        "routes_rounds": _write(tmp_path / "routes-rounds.v1.json", routes_rounds),
        "challenge": _write(tmp_path / "challenge.v2.json", _challenge(catalog)),
    }


def _args(paths: dict[str, Path]) -> list[str]:
    return [
        "validate-public-artifacts",
        "--catalog",
        str(paths["catalog"]),
        "--album-art",
        str(paths["album_art"]),
        "--connection-universe",
        str(paths["connection_universe"]),
        "--connection-rounds",
        str(paths["connection_rounds"]),
        "--daily-manifest",
        str(paths["daily_manifest"]),
        "--routes-universe",
        str(paths["routes_universe"]),
        "--routes-rounds",
        str(paths["routes_rounds"]),
        "--challenge",
        str(paths["challenge"]),
    ]


def test_clean_set_exits_zero(tmp_path: Path, capsys) -> None:
    paths = _write_all(tmp_path)
    exit_code = main(_args(paths))
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["failures"] == {
        "catalog": [],
        "album_art_registry": [],
        "connection_guesser": [],
        "connection_daily_manifest": [],
        "record_routes": [],
        "challenge": [],
    }


def test_broken_artifact_exits_one(tmp_path: Path, capsys) -> None:
    paths = _write_all(tmp_path)
    broken = json.loads(paths["routes_universe"].read_text())
    del broken["mode"]
    paths["routes_universe"].write_text(json.dumps(broken))

    exit_code = main(_args(paths))
    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["failures"]["record_routes"] != []
    assert report["failures"]["catalog"] == []


def test_default_paths_point_at_the_real_repo_layout(tmp_path: Path, capsys, monkeypatch) -> None:
    """The zero-argument form must resolve to the actual committed file
    layout when run from the repo root -- confirms the CI-facing default
    wiring end-to-end, not just that explicit overrides work."""
    catalog = _catalog()
    routes_universe, routes_rounds = _routes_pair()
    layout = {
        "apps/web/public/data/catalog/albums.v1.json": catalog,
        "apps/web/public/data/catalog/album-art.v1.json": _album_art(catalog),
        "apps/web/public/data/game/universe.v1.json": _connection_universe(),
        "apps/web/public/data/game/rounds.v1.json": _connection_rounds(),
        "apps/web/public/data/game/daily-manifest.v1.json": _daily_manifest(),
        "apps/web/public/data/routes/universe.v1.json": routes_universe,
        "apps/web/public/data/routes/rounds.v1.json": routes_rounds,
        "apps/web/public/data/challenge.v2.json": _challenge(catalog),
    }
    for relative_path, payload in layout.items():
        full_path = tmp_path / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(json.dumps(payload))

    monkeypatch.chdir(tmp_path)
    exit_code = main(["validate-public-artifacts"])
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
