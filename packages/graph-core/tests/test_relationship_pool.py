"""Unit tests for the relationship-based candidate pool (graph-expansion
Phase 2 "Pool B", plan section 21.3 slice X2) -- masters that share performers
with the published catalog, as opposed to `rank_album_candidates`' popularity
ranking."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import SNAPSHOT_DATE, write_synthetic_dataset, write_synthetic_masters
from networked_players_graph_core.relationship_pool import build_relationship_pool


def _release(release_id: int, *, master_id: int):
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Release {release_id}",
        "country": None,
        "released": "2001",
        "master_id": master_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int,
    *,
    artist_id: int,
    name: str,
    credit_scope: str = "release_credit",
    role_text: str | None = "Guitar",
):
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
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


def _master_row(master_id: int, *, main_release_id: int, genres=None, styles=None, year=2001):
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "master_id": master_id,
        "main_release_id": main_release_id,
        "title": f"Master {master_id}",
        "year": year,
        "genres": genres or ["Rock"],
        "styles": styles or ["Pop Rock"],
        "data_quality": None,
        "source_url": f"https://example.invalid/master/{master_id}",
    }


# Catalog performers 100 and 200 are already on published albums.
_CATALOG_PERFORMERS = [100, 200]


@pytest.fixture
def dataset(tmp_path: Path) -> tuple[Path, Path]:
    """900 -- two catalog performers (overlap 2, qualifies at the default)
    901 -- one catalog performer (overlap 1, below the default threshold)
    902 -- two catalog performers but a non-studio master genre
    903 -- two catalog performers, but both credited in NON-performer roles
    904 -- two catalog performers, but no billed release artist to publish under
    """
    dataset_root = write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}",
        release_rows=[
            _release(rid, master_id=900 + i) for i, rid in enumerate([10, 11, 12, 13, 14])
        ],
        credit_rows=[
            _credit(
                10, artist_id=999, name="Billed", credit_scope="release_artist", role_text=None
            ),
            _credit(10, artist_id=100, name="Alice"),
            _credit(10, artist_id=200, name="Bob"),
            _credit(
                11, artist_id=998, name="Billed2", credit_scope="release_artist", role_text=None
            ),
            _credit(11, artist_id=100, name="Alice"),
            _credit(
                12, artist_id=997, name="Billed3", credit_scope="release_artist", role_text=None
            ),
            _credit(12, artist_id=100, name="Alice"),
            _credit(12, artist_id=200, name="Bob"),
            # Sleeve design and mastering are not performances (ADR 0068).
            _credit(
                13, artist_id=996, name="Billed4", credit_scope="release_artist", role_text=None
            ),
            _credit(13, artist_id=100, name="Alice", role_text="Design"),
            _credit(13, artist_id=200, name="Bob", role_text="Mastered By"),
            # No release_artist credit at all on 14.
            _credit(14, artist_id=100, name="Alice"),
            _credit(14, artist_id=200, name="Bob"),
        ],
    )
    masters_root = write_synthetic_masters(
        tmp_path / "masters",
        master_rows=[
            _master_row(900, main_release_id=10),
            _master_row(901, main_release_id=11),
            _master_row(902, main_release_id=12, genres=["Stage & Screen"]),
            _master_row(903, main_release_id=13),
            _master_row(904, main_release_id=14),
        ],
    )
    return dataset_root, masters_root


_ALLOWED = frozenset({10, 11, 12, 13, 14})


def _pool(dataset, **kwargs):
    dataset_root, masters_root = dataset
    return build_relationship_pool(
        dataset_root,
        catalog_performer_ids=_CATALOG_PERFORMERS,
        masters_root=masters_root,
        allowed_release_ids=_ALLOWED,
        quiet=True,
        **kwargs,
    )


def test_only_masters_meeting_the_overlap_threshold_enter_the_pool(dataset) -> None:
    rows = _pool(dataset)
    by_master = {row["master_id"]: row for row in rows}

    # 900 alone qualifies: 901 has overlap 1, 902 is non-studio, 903's shared
    # artists are non-performers, 904 has nothing billed to publish under.
    assert sorted(by_master) == [900]
    assert by_master[900]["catalog_performer_overlap"] == 2
    assert by_master[900]["artist_id"] == 999
    assert by_master[900]["artist_name"] == "Billed"
    assert by_master[900]["main_release_id"] == 10
    assert by_master[900]["sample_title"] == "Master 900"
    assert by_master[900]["year"] == 2001


def test_relaxing_the_threshold_admits_single_overlap_masters(dataset) -> None:
    """`expansion-policy-v1.json`'s collection_relaxation drops the minimum to
    1 -- the pool must honour that rather than hardcoding the automatic-lane
    threshold."""
    rows = _pool(dataset, minimum_overlap=1)
    by_master = {row["master_id"]: row for row in rows}
    assert 901 in by_master
    assert by_master[901]["catalog_performer_overlap"] == 1


def test_non_performer_credits_never_count_as_overlap(dataset) -> None:
    """Master 903 shares both catalog artists, but only as Design and
    Mastered By -- ADR 0068's performer gate, the same rule
    edge_eligible_membership_artist_ids applies on the scoring side, so the
    pool and the score cannot disagree about who counts."""
    rows = _pool(dataset, minimum_overlap=1)
    assert 903 not in {row["master_id"] for row in rows}


def test_exclusions_and_already_published_masters_are_dropped(dataset) -> None:
    assert _pool(dataset, already_published_master_ids=frozenset({900})) == []
    assert _pool(dataset, master_exclusions=frozenset({900})) == []


def test_output_is_rank_album_candidates_shaped_and_deterministic(dataset) -> None:
    """The pool substitutes for rank-album-candidates' output, so it must carry
    the keys both consumers index -- greedy_marginal_selection reads
    artist_id/main_release_id/master_id directly."""
    first = _pool(dataset, minimum_overlap=1)
    assert first == _pool(dataset, minimum_overlap=1)

    required = {"master_id", "artist_id", "artist_name", "sample_title", "main_release_id", "year"}
    for row in first:
        assert required <= set(row)
        assert row["artist_id"] is not None
        assert row["main_release_id"] is not None

    overlaps = [row["catalog_performer_overlap"] for row in first]
    assert overlaps == sorted(overlaps, reverse=True)


def test_an_empty_performer_set_is_refused(dataset) -> None:
    """Silently returning an empty pool would look like "no candidates exist"
    -- the exact failure mode this whole slice exists to prevent."""
    dataset_root, masters_root = dataset
    with pytest.raises(ValueError, match="catalog_performer_ids is empty"):
        build_relationship_pool(
            dataset_root,
            catalog_performer_ids=[],
            masters_root=masters_root,
            allowed_release_ids=_ALLOWED,
            quiet=True,
        )
