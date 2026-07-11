from __future__ import annotations

from pathlib import Path

from networked_players_graph_core.analysis import rank_album_candidates


def test_rank_album_candidates_orders_by_variant_times_credit_richness(dataset_root: Path) -> None:
    candidates = rank_album_candidates(dataset_root)

    by_master = {c["master_id"]: c for c in candidates}
    # Master 901 (release 1): 1 variant, and 4 credit rows -- Alice and Bob each
    # hold a release_artist row and a track_artist row -> score 4.
    assert by_master[901]["variant_count"] == 1
    assert by_master[901]["credit_rows"] == 4
    assert by_master[901]["score"] == 4

    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_rank_album_candidates_respects_limit(dataset_root: Path) -> None:
    candidates = rank_album_candidates(dataset_root, limit=1)
    assert len(candidates) == 1
