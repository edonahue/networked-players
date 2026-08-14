from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.evidence_release_registry import (
    CAVEAT_FLAG_NAMES,
    build_evidence_release_registry,
)
from networked_players_graph_core.graph import CreditGraph

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist_id": 100, "main_release_id": 1}
        ],
    }


def _release_row(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": "US",
        "released": "1995-01-01",
        "master_id": release_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _format_row(
    release_id: int, descriptions: list[str], *, format_index: int = 0
) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "format_index": format_index,
        "format_name": "Vinyl",
        "quantity": 1,
        "format_text": None,
        "descriptions": descriptions,
    }


def _challenge_release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "title": title,
        "country": "US",
        "released": "1995-01-01",
        "master_id": release_id,
        "source_url": "https://data.discogs.com/?download=fake",
    }


def _album_art() -> dict[str, Any]:
    return {
        "albums": [
            {
                "album_id": "master-1",
                "main_release_id": 1,
                "uri150": "https://i.discogs.com/thumb.jpg",
                "uri": "https://i.discogs.com/full.jpg",
                "width": 600,
                "height": 600,
            }
        ]
    }


def test_union_covers_all_three_sources() -> None:
    challenge = {"releases": [_challenge_release(1, "Challenge Release")]}
    routes_rounds = {"releases": [_challenge_release(2, "Routes Release")]}
    pathfinding_graph = {"evidence_release_ids": [1, 2]}
    payload = build_evidence_release_registry(
        None,
        challenge=challenge,
        routes_rounds=routes_rounds,
        pathfinding_graph=pathfinding_graph,
        album_art=_album_art(),
        catalog=_catalog(),
        generated_at="2026-08-07T00:00:00+00:00",
    )
    assert payload["release_ids"] == [1, 2]
    assert payload["titles"] == ["Challenge Release", "Routes Release"]


def test_pathfinding_only_release_resolved_via_graph(tmp_path: Path) -> None:
    """Release 2 appears only in the pathfinding graph's evidence_release_ids
    -- its metadata must come from a real CreditGraph lookup, not from
    challenge/routes (which don't mention it)."""
    from conftest import write_synthetic_dataset

    releases = [
        {
            "snapshot_date": _SNAPSHOT,
            "release_id": 2,
            "status": "Accepted",
            "title": "Graph-Only Release",
            "country": "GB",
            "released": "1998",
            "master_id": 2,
            "master_is_main_release": True,
            "data_quality": "Correct",
            "source_url": "https://data.discogs.com/?download=fake",
        }
    ]
    credits = [
        {
            "snapshot_date": _SNAPSHOT,
            "release_id": 2,
            "track_index": None,
            "track_path": None,
            "track_position": None,
            "track_title": None,
            "credit_scope": "release_artist",
            "artist_id": 200,
            "name": "Bob",
            "anv": None,
            "join_text": None,
            "role_text": None,
            "credited_tracks_text": None,
            "is_linked": True,
            "playable_identity": True,
        }
    ]
    onehop = write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )

    challenge = {"releases": [_challenge_release(1, "Challenge Release")]}
    routes_rounds = {"releases": []}
    pathfinding_graph = {"evidence_release_ids": [1, 2]}
    with CreditGraph.open(onehop) as graph:
        payload = build_evidence_release_registry(
            graph,
            challenge=challenge,
            routes_rounds=routes_rounds,
            pathfinding_graph=pathfinding_graph,
            album_art=_album_art(),
            catalog=_catalog(),
            generated_at="2026-08-07T00:00:00+00:00",
        )
    by_id = dict(zip(payload["release_ids"], payload["titles"], strict=True))
    assert by_id[2] == "Graph-Only Release"


def test_missing_release_with_no_graph_raises() -> None:
    challenge = {"releases": []}
    routes_rounds = {"releases": []}
    pathfinding_graph = {"evidence_release_ids": [999]}
    with pytest.raises(ValueError, match="graph was None"):
        build_evidence_release_registry(
            None,
            challenge=challenge,
            routes_rounds=routes_rounds,
            pathfinding_graph=pathfinding_graph,
            album_art=_album_art(),
            catalog=_catalog(),
            generated_at="2026-08-07T00:00:00+00:00",
        )


def test_cover_art_only_for_catalog_main_release() -> None:
    challenge = {
        "releases": [_challenge_release(1, "Catalog Album"), _challenge_release(2, "Other")]
    }
    routes_rounds = {"releases": []}
    pathfinding_graph = {"evidence_release_ids": [1, 2]}
    payload = build_evidence_release_registry(
        None,
        challenge=challenge,
        routes_rounds=routes_rounds,
        pathfinding_graph=pathfinding_graph,
        album_art=_album_art(),
        catalog=_catalog(),
        generated_at="2026-08-07T00:00:00+00:00",
    )
    by_id = dict(zip(payload["release_ids"], payload["cover_uri150s"], strict=True))
    assert by_id[1] == "https://i.discogs.com/thumb.jpg"
    assert by_id[2] is None


def test_relation_to_catalog_album_ids() -> None:
    challenge = {
        "releases": [_challenge_release(1, "Catalog Album"), _challenge_release(2, "Other")]
    }
    routes_rounds = {"releases": []}
    pathfinding_graph = {"evidence_release_ids": [1, 2]}
    payload = build_evidence_release_registry(
        None,
        challenge=challenge,
        routes_rounds=routes_rounds,
        pathfinding_graph=pathfinding_graph,
        album_art=_album_art(),
        catalog=_catalog(),
        generated_at="2026-08-07T00:00:00+00:00",
    )
    by_id = dict(zip(payload["release_ids"], payload["relation_to_catalog_album_ids"], strict=True))
    assert by_id[1] == "master-1"
    assert by_id[2] is None


def test_year_extraction_handles_full_dates_and_year_only_and_none() -> None:
    challenge = {
        "releases": [
            {**_challenge_release(1, "Full Date"), "released": "1989-06-06"},
            {**_challenge_release(2, "Year Only"), "released": "1995"},
            {**_challenge_release(3, "No Date"), "released": None},
        ]
    }
    routes_rounds = {"releases": []}
    pathfinding_graph = {"evidence_release_ids": [1, 2, 3]}
    payload = build_evidence_release_registry(
        None,
        challenge=challenge,
        routes_rounds=routes_rounds,
        pathfinding_graph=pathfinding_graph,
        album_art=_album_art(),
        catalog=_catalog(),
        generated_at="2026-08-07T00:00:00+00:00",
    )
    by_id = dict(zip(payload["release_ids"], payload["years"], strict=True))
    assert by_id == {1: 1989, 2: 1995, 3: None}


def test_top_level_shape_and_version() -> None:
    challenge = {"releases": [_challenge_release(1, "R")]}
    routes_rounds = {"releases": []}
    pathfinding_graph = {"evidence_release_ids": [1]}
    payload = build_evidence_release_registry(
        None,
        challenge=challenge,
        routes_rounds=routes_rounds,
        pathfinding_graph=pathfinding_graph,
        album_art=_album_art(),
        catalog=_catalog(),
        generated_at="2026-08-07T00:00:00+00:00",
    )
    assert payload["schema_version"] == 2
    assert payload["catalog_version"] == _CATALOG_VERSION
    assert payload["evidence_release_registry_version"].startswith(
        f"evidence-release-registry-v2-{_SNAPSHOT}-"
    )
    # The legend ships with the data so the integers are self-describing.
    assert payload["caveat_flag_names"] == list(CAVEAT_FLAG_NAMES)
    # `graph=None` means no `release_formats` lookup was possible at all.
    # That must read as "nothing warrants a caveat", not as a build failure
    # and not as a positive quality claim.
    assert payload["caveat_flags"] == [0]


def test_deterministic_across_repeated_builds() -> None:
    challenge = {"releases": [_challenge_release(1, "R")]}
    routes_rounds = {"releases": []}
    pathfinding_graph = {"evidence_release_ids": [1]}
    kwargs = dict(
        challenge=challenge,
        routes_rounds=routes_rounds,
        pathfinding_graph=pathfinding_graph,
        album_art=_album_art(),
        catalog=_catalog(),
        generated_at="2026-08-07T00:00:00+00:00",
    )
    first = build_evidence_release_registry(None, **kwargs)
    second = build_evidence_release_registry(None, **kwargs)
    assert first == second


def test_caveat_flags_come_from_the_dataset_not_from_a_default(tmp_path: Path) -> None:
    """The one path with no coverage until now: a real `CreditGraph` ->
    `format_descriptors_for_ids` -> `caveat_flags`.

    This matters more than a normal wiring test because `0` is defined to
    mean "nothing warrants a caveat" AND is what an absent lookup produces.
    A regression that made the lookup miss every id -- key-type drift, a
    `release_formats` relation that silently binds empty -- would publish
    an all-zero flag array that passes every other test, the contract
    validator and the Pi-fleet check, silently disarming the single signal
    PR 3's ranking and PR 5's caveats both depend on. Only a non-zero
    assertion sourced from real dataset rows can catch that.
    """
    from conftest import write_synthetic_dataset

    dataset = write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}",
        release_rows=[_release_row(1, "First Light"), _release_row(7, "Some Other Record")],
        # `CreditGraph.open` refuses a dataset with no credit rows at all,
        # so this is the minimum to make the fixture a real one -- the
        # registry itself reads releases and formats, never credits.
        credit_rows=[
            {
                "snapshot_date": _SNAPSHOT,
                "release_id": 1,
                "track_index": None,
                "track_path": None,
                "track_position": None,
                "track_title": None,
                "credit_scope": "release_artist",
                "artist_id": 100,
                "name": "Alice",
                "anv": None,
                "join_text": None,
                "role_text": None,
                "credited_tracks_text": None,
                "is_linked": True,
                "playable_identity": True,
            }
        ],
        release_format_rows=[
            _format_row(1, ["Album"]),
            # Two rows for one release: a 2xCD + DVD box set is several
            # `release_formats` rows, and the flags must union across them.
            _format_row(7, ["Compilation"]),
            _format_row(7, ["Unofficial Release"], format_index=1),
        ],
    )
    challenge = {"releases": [_challenge_release(1, "First Light")]}
    with CreditGraph.open(dataset, build_edges=False) as graph:
        payload = build_evidence_release_registry(
            graph,
            challenge=challenge,
            routes_rounds={"releases": []},
            pathfinding_graph={"evidence_release_ids": [1, 7]},
            album_art=_album_art(),
            catalog=_catalog(),
            generated_at="2026-08-14T00:00:00+00:00",
        )

    flags = dict(zip(payload["release_ids"], payload["caveat_flags"], strict=True))
    compilation = CAVEAT_FLAG_NAMES.index("compilation")
    unofficial = CAVEAT_FLAG_NAMES.index("unofficial")
    assert flags[7] == (1 << compilation) | (1 << unofficial), (
        "flags must union across a release's several format rows, and must "
        "come from the dataset rather than defaulting to 0"
    )
    # A release tagged only `Album` carries no caveat -- and that is the
    # ONLY thing it means. It is not a positive studio-album claim.
    assert flags[1] == 0
