"""`assemble_album_catalog(approved_pool=...)`: the checked approval boundary
(ADR 0072 section 2). Synthetic fixtures only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.analysis import (
    ApprovedPoolError,
    assemble_album_catalog,
    rank_album_candidates,
)
from networked_players_graph_core.graph import CreditGraph

EDITORIAL = [{"artist": "Alice", "title": "First Light"}]  # master 901


def _pre(master_id: int, artist_id: int, artist: str, title: str) -> dict[str, Any]:
    return {
        "query_artist": artist,
        "query_title": title,
        "master_id": master_id,
        "main_release_id": master_id,
        "artist_id": artist_id,
        "artist": artist,
        "title": title,
        "year": 2000,
    }


def _pool(*entries: tuple[int, int, str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "note": "synthetic",
        "albums": [
            {"master_id": m, "round": r, "selection_source": s} for m, r, s in sorted(entries)
        ],
    }


# Alice's album is ALSO in the already-published lane, as in the real catalog:
# the top-albums lane runs first and keeps the 'editorial' label.
PUBLISHED = [_pre(901, 100, "Alice", "First Light"), _pre(9001, 700, "Fictoquai", "Kept")]
FEATURED = frozenset({9001})
GOOD_POOL = _pool((901, 0, "editorial"), (9001, 0, "already_published"))


def _build(dataset_root: Path, **kwargs: Any) -> dict[str, Any]:
    editorial = kwargs.pop("editorial", EDITORIAL)
    candidates = kwargs.pop("candidates", [])
    target_count = kwargs.pop("target_count", 10)
    with CreditGraph.open(dataset_root) as graph:
        return assemble_album_catalog(
            graph,
            editorial,
            candidates,
            target_count=target_count,
            additional_pre_resolved=[("already_published", PUBLISHED, False)],
            featured_master_ids=FEATURED,
            expansion_round=1,
            previously_published_rounds={901: 0, 9001: 0},
            **kwargs,
        )


def test_supplying_a_pool_does_not_change_any_album_or_label(dataset_root: Path) -> None:
    """Label stability: the pool is a post-hoc check. The top-albums lane still
    runs before already_published and labels master 901 'editorial'; every
    album dict is identical with and without the pool."""
    without = _build(dataset_root)
    with_pool = _build(dataset_root, approved_pool=GOOD_POOL)
    assert with_pool["albums"] == without["albums"]
    labels = {a["master_id"]: a["selection_source"] for a in with_pool["albums"]}
    assert labels == {901: "editorial", 9001: "already_published"}
    assert with_pool["catalog_version"] == without["catalog_version"]


def test_without_editorial_lane_the_label_differs_and_the_pool_catches_it(
    dataset_root: Path,
) -> None:
    """If the operator omits --editorial-albums with a pool, master 901 would be
    labelled already_published; the check fails loudly instead of relabelling."""
    with pytest.raises(ApprovedPoolError, match="selection_source"):
        _build(dataset_root, editorial=[], approved_pool=GOOD_POOL)


def test_an_unapproved_album_fails_naming_it(dataset_root: Path) -> None:
    with pytest.raises(ApprovedPoolError, match=r"not approved.*9001.*Fictoquai"):
        _build(dataset_root, approved_pool=_pool((901, 0, "editorial")))


def test_an_approved_album_dropped_for_eligibility_fails_with_the_reason(
    dataset_root: Path,
) -> None:
    with pytest.raises(ApprovedPoolError, match=r"absent from the result.*9001.*dropped"):
        _build(dataset_root, approved_pool=GOOD_POOL, master_exclusions=frozenset({9001}))


def test_an_approved_album_nobody_supplied_fails(dataset_root: Path) -> None:
    pool = _pool((901, 0, "editorial"), (9001, 0, "already_published"), (5555, 1, "graph_rich"))
    with pytest.raises(ApprovedPoolError, match=r"absent from the result.*5555"):
        _build(dataset_root, approved_pool=pool)


def test_shortlist_auto_fill_is_disabled_with_a_pool(dataset_root: Path) -> None:
    candidates = rank_album_candidates(dataset_root)
    filled = _build(dataset_root, candidates=candidates)
    assert filled["candidate_count_added"] > 0  # today's behavior fills
    with_pool = _build(dataset_root, candidates=candidates, approved_pool=GOOD_POOL)
    assert with_pool["candidate_count_added"] == 0
    assert {a["master_id"] for a in with_pool["albums"]} == {901, 9001}


def test_a_malformed_pool_is_refused(dataset_root: Path) -> None:
    with pytest.raises(ApprovedPoolError, match="malformed"):
        _build(dataset_root, approved_pool={"schema_version": 1, "albums": []})
