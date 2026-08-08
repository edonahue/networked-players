from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.album_credit_membership import build_album_credit_membership
from networked_players_graph_core.graph import CreditGraph

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
    is_linked: bool = True,
) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": str(track_index) if track_index is not None else None,
        "track_position": "1" if track_index is not None else None,
        "track_title": "Take" if track_index is not None else None,
        "credit_scope": credit_scope,
        "artist_id": artist_id if is_linked else None,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": is_linked,
        "playable_identity": is_linked,
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


@pytest.fixture
def onehop_dataset(tmp_path: Path) -> Path:
    """Two catalog albums (release 1 -> Alice, release 2 -> Bob), each with
    a real credit plus one unlinked (artist_id-less) credit row that must
    never appear in the built membership -- confirming the linked-only
    filter this artifact deliberately inherits from
    `credit_rows_for_releases`."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1"), _release(2, "R2")]
    credits = [
        _credit(1, 100, "Alice", credit_scope="release_artist"),
        _credit(1, 100, "Alice", credit_scope="track_artist", track_index=0, role_text="Producer"),
        _credit(1, 999, "Unlinked Name", is_linked=False),
        _credit(2, 200, "Bob", credit_scope="release_artist"),
        _credit(2, 200, "Bob", credit_scope="track_artist", track_index=0, role_text="Vocals"),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist_id": 100, "main_release_id": 1},
            {"id": "master-2", "title": "Second Wind", "artist_id": 200, "main_release_id": 2},
        ],
    }


def test_every_catalog_album_present_with_its_own_release_credits(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_album_credit_membership(
            graph, _catalog(), generated_at="2026-08-07T00:00:00+00:00"
        )

    by_id = {a["album_id"]: a for a in payload["albums"]}
    assert set(by_id) == {"master-1", "master-2"}
    assert by_id["master-1"]["main_release_id"] == 1
    assert {c["artist_id"] for c in by_id["master-1"]["credits"]} == {100}
    assert by_id["master-2"]["main_release_id"] == 2
    assert {c["artist_id"] for c in by_id["master-2"]["credits"]} == {200}


def test_main_release_id_never_re_derived(onehop_dataset: Path) -> None:
    """The artifact must echo the catalog's own main_release_id exactly,
    never recompute it from the graph."""
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_album_credit_membership(
            graph, _catalog(), generated_at="2026-08-07T00:00:00+00:00"
        )
    for album in payload["albums"]:
        catalog_album = next(a for a in _catalog()["albums"] if a["id"] == album["album_id"])
        assert album["main_release_id"] == catalog_album["main_release_id"]


def test_unlinked_credits_are_excluded(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_album_credit_membership(
            graph, _catalog(), generated_at="2026-08-07T00:00:00+00:00"
        )
    all_names = {c["name"] for album in payload["albums"] for c in album["credits"]}
    assert "Unlinked Name" not in all_names


def test_album_with_thin_credits_still_appears(tmp_path: Path) -> None:
    """Release 1 (the catalog album under test) has zero credit rows; a
    real credit row on an unrelated release 2 keeps the dataset itself
    non-empty (CreditGraph.open refuses a dataset with zero credit rows
    outright, a separate, unrelated safety check)."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1"), _release(2, "R2")]
    credits = [_credit(2, 999, "Unrelated Artist")]
    onehop = write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )
    catalog = {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist_id": 100, "main_release_id": 1}
        ],
    }
    with CreditGraph.open(onehop) as graph:
        payload = build_album_credit_membership(
            graph, catalog, generated_at="2026-08-07T00:00:00+00:00"
        )
    assert payload["albums"] == [{"album_id": "master-1", "main_release_id": 1, "credits": []}]


def test_top_level_shape_and_version(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_album_credit_membership(
            graph, _catalog(), generated_at="2026-08-07T00:00:00+00:00"
        )
    assert payload["schema_version"] == 1
    assert payload["catalog_version"] == _CATALOG_VERSION
    assert payload["album_credit_membership_version"].startswith(
        f"album-credit-membership-v1-{_SNAPSHOT}-"
    )


def test_deterministic_across_repeated_builds(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        first = build_album_credit_membership(
            graph, _catalog(), generated_at="2026-08-07T00:00:00+00:00"
        )
    with CreditGraph.open(onehop_dataset) as graph:
        second = build_album_credit_membership(
            graph, _catalog(), generated_at="2026-08-07T00:00:00+00:00"
        )
    assert first == second


def test_no_albums_raises() -> None:
    empty_catalog = {"catalog_version": _CATALOG_VERSION, "snapshot_date": _SNAPSHOT, "albums": []}
    with pytest.raises(ValueError, match="no albums"):
        build_album_credit_membership(
            None,  # type: ignore[arg-type]
            empty_catalog,
            generated_at="2026-08-07T00:00:00+00:00",
        )


def test_catalog_version_mismatch_is_not_silently_accepted(onehop_dataset: Path) -> None:
    """The builder trusts the catalog it's given -- a wrong catalog_version
    stamped through unchanged is the validator's job to catch, not this
    function's, but the output must still faithfully echo whatever catalog
    it was actually given rather than inventing its own version."""
    catalog = _catalog()
    catalog["catalog_version"] = "catalog-v1-20260601-deadbeefdead"
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_album_credit_membership(
            graph, catalog, generated_at="2026-08-07T00:00:00+00:00"
        )
    assert payload["catalog_version"] == "catalog-v1-20260601-deadbeefdead"
