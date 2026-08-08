from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.pathfinding_graph import build_pathfinding_graph

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _credit(
    release_id: int,
    artist_id: int,
    name: str,
    *,
    credit_scope: str = "release_artist",
    track_index: int | None = None,
    role_text: str | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": str(track_index) if track_index is not None else None,
        "track_position": "1" if track_index is not None else None,
        "track_title": "Take" if track_index is not None else None,
        "credit_scope": credit_scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": None,
        "master_id": release_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _co_performer_credits(
    release_id: int, a: tuple[int, str, str], b: tuple[int, str, str]
) -> list[dict[str, Any]]:
    a_id, a_name, a_role = a
    b_id, b_name, b_role = b
    return [
        _credit(release_id, a_id, a_name, credit_scope="release_artist"),
        _credit(
            release_id, a_id, a_name, credit_scope="track_artist", track_index=0, role_text=a_role
        ),
        _credit(release_id, b_id, b_name, credit_scope="release_artist"),
        _credit(
            release_id, b_id, b_name, credit_scope="track_artist", track_index=0, role_text=b_role
        ),
    ]


@pytest.fixture
def onehop_dataset(tmp_path: Path) -> Path:
    """Alice (seed artist, album master-1) co-performs with Bob (release 1)
    and with Carol (release 2) -- Bob and Carol are one hop out from the
    catalog's only seed artist and must appear in the pathfinding graph."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1"), _release(2, "R2")]
    credits = [
        *_co_performer_credits(1, (100, "Alice", "Guitar"), (200, "Bob", "Bass")),
        *_co_performer_credits(2, (100, "Alice", "Producer"), (300, "Carol", "Vocals")),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [{"id": "master-1", "title": "First Light", "artist_id": 100, "year": 1995}],
    }


def test_pathfinding_graph_includes_the_1hop_neighborhood(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph, _catalog(), snapshot_date=_SNAPSHOT, generated_at="2026-08-03T00:00:00+00:00"
        )

    assert set(payload["node_ids"]) == {100, 200, 300}
    name_by_id = dict(zip(payload["node_ids"], payload["names"], strict=True))
    assert name_by_id == {100: "Alice", 200: "Bob", 300: "Carol"}


def test_edge_roles_carry_real_role_text_for_both_endpoints(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph, _catalog(), snapshot_date=_SNAPSHOT, generated_at="2026-08-03T00:00:00+00:00"
        )

    node_ids = payload["node_ids"]
    by_pair: dict[tuple[int, int], tuple[str, str]] = {}
    for node_index in range(len(node_ids)):
        start, end = payload["offsets"][node_index], payload["offsets"][node_index + 1]
        artist_a_id = node_ids[node_index]
        for slot in range(start, end):
            neighbor_index = payload["neighbors"][slot]
            artist_b_id = node_ids[neighbor_index]
            by_pair[(artist_a_id, artist_b_id)] = (
                payload["edge_role_a"][slot],
                payload["edge_role_b"][slot],
            )

    assert by_pair[(100, 200)] == ("Guitar", "Bass")
    assert by_pair[(200, 100)] == ("Bass", "Guitar")
    assert by_pair[(100, 300)] == ("Producer", "Vocals")
    assert by_pair[(300, 100)] == ("Vocals", "Producer")


@pytest.fixture
def two_role_dataset(tmp_path: Path) -> Path:
    """Alice holds two distinct track_artist role credits on release 1
    (Guitar on one track, Keys on another) alongside Bob's single Bass
    credit -- the edge role text for (100, 200) must join both of Alice's
    roles, not silently keep only the first."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1")]
    credits = [
        _credit(1, 100, "Alice", credit_scope="release_artist"),
        _credit(1, 100, "Alice", credit_scope="track_artist", track_index=0, role_text="Guitar"),
        _credit(1, 100, "Alice", credit_scope="track_artist", track_index=1, role_text="Keys"),
        _credit(1, 200, "Bob", credit_scope="release_artist"),
        _credit(1, 200, "Bob", credit_scope="track_artist", track_index=0, role_text="Bass"),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


def test_edge_role_joins_multiple_distinct_roles(two_role_dataset: Path) -> None:
    with CreditGraph.open(two_role_dataset) as graph:
        payload = build_pathfinding_graph(
            graph, _catalog(), snapshot_date=_SNAPSHOT, generated_at="2026-08-07T00:00:00+00:00"
        )

    node_ids = payload["node_ids"]
    by_pair: dict[tuple[int, int], tuple[str, str]] = {}
    for node_index in range(len(node_ids)):
        start, end = payload["offsets"][node_index], payload["offsets"][node_index + 1]
        artist_a_id = node_ids[node_index]
        for slot in range(start, end):
            neighbor_index = payload["neighbors"][slot]
            artist_b_id = node_ids[neighbor_index]
            by_pair[(artist_a_id, artist_b_id)] = (
                payload["edge_role_a"][slot],
                payload["edge_role_b"][slot],
            )

    assert by_pair[(100, 200)] == ("Guitar; Keys", "Bass")
    assert by_pair[(200, 100)] == ("Bass", "Guitar; Keys")


@pytest.fixture
def many_role_dataset(tmp_path: Path) -> Path:
    """Alice holds 30 distinct, verbose role credits on release 1 -- a real
    corpus measurement found joining every distinct role unbounded can
    reach 2,639 characters for a busy multi-track release. The joined
    result must stay bounded (`_MAX_JOINED_ROLE_LEN`), not grow without
    limit."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1")]
    credits = [_credit(1, 100, "Alice", credit_scope="release_artist")]
    for i in range(30):
        credits.append(
            _credit(
                1,
                100,
                "Alice",
                credit_scope="track_artist",
                track_index=i,
                role_text=f"Producer, Piano, Backing Vocals [Variant {i}]",
            )
        )
    credits.append(_credit(1, 200, "Bob", credit_scope="release_artist"))
    credits.append(
        _credit(1, 200, "Bob", credit_scope="track_artist", track_index=0, role_text="Bass")
    )
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


def test_edge_role_join_stays_bounded(many_role_dataset: Path) -> None:
    with CreditGraph.open(many_role_dataset) as graph:
        payload = build_pathfinding_graph(
            graph, _catalog(), snapshot_date=_SNAPSHOT, generated_at="2026-08-07T00:00:00+00:00"
        )

    node_ids = payload["node_ids"]
    alice_index = node_ids.index(100)
    start, end = payload["offsets"][alice_index], payload["offsets"][alice_index + 1]
    role_for_bob = next(
        payload["edge_role_a"][slot]
        for slot in range(start, end)
        if node_ids[payload["neighbors"][slot]] == 200
    )
    assert len(role_for_bob) <= 201  # _MAX_JOINED_ROLE_LEN + the trailing ellipsis character
    assert role_for_bob.endswith("…")


def test_top_level_shape_and_version(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph, _catalog(), snapshot_date=_SNAPSHOT, generated_at="2026-08-03T00:00:00+00:00"
        )
    assert payload["schema_version"] == 1
    assert payload["catalog_version"] == _CATALOG_VERSION
    assert payload["pathfinding_graph_version"].startswith(f"pathfinding-graph-v1-{_SNAPSHOT}-")


def test_deterministic_across_repeated_builds(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        first = build_pathfinding_graph(
            graph, _catalog(), snapshot_date=_SNAPSHOT, generated_at="2026-08-03T00:00:00+00:00"
        )
    with CreditGraph.open(onehop_dataset) as graph:
        second = build_pathfinding_graph(
            graph, _catalog(), snapshot_date=_SNAPSHOT, generated_at="2026-08-03T00:00:00+00:00"
        )
    assert first == second


def test_no_albums_raises() -> None:
    empty_catalog = {"catalog_version": _CATALOG_VERSION, "snapshot_date": _SNAPSHOT, "albums": []}
    with pytest.raises(ValueError, match="no albums"):
        # A real graph isn't even needed -- this must fail before querying it.
        build_pathfinding_graph(
            None,  # type: ignore[arg-type]
            empty_catalog,
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-03T00:00:00+00:00",
        )
