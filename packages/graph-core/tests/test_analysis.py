from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_graph_core.analysis import assemble_album_catalog, rank_album_candidates
from networked_players_graph_core.graph import CreditGraph


def test_rank_album_candidates_orders_by_variant_times_credit_richness(dataset_root: Path) -> None:
    candidates = rank_album_candidates(dataset_root)

    by_master = {c["master_id"]: c for c in candidates}
    # Master 901 (release 1): 1 variant, and 4 credit rows -- Alice and Bob each
    # hold a release_artist row and a track_artist row -> score 4.
    assert by_master[901]["variant_count"] == 1
    assert by_master[901]["credit_rows"] == 4
    assert by_master[901]["score"] == 4
    # Resolved to a real {artist, title} query pair -- Alice has the lower
    # artist_id of the two release_artist credits on release 1.
    assert by_master[901]["main_release_id"] == 1
    assert by_master[901]["artist_id"] == 100
    assert by_master[901]["artist_name"] == "Alice"
    assert by_master[901]["sample_title"] == "First Light"

    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_rank_album_candidates_respects_limit(dataset_root: Path) -> None:
    candidates = rank_album_candidates(dataset_root, limit=1)
    assert len(candidates) == 1


def test_rank_album_candidates_applies_release_format_policy(
    dataset_root: Path, tmp_path: Path
) -> None:
    policy_path = tmp_path / "release-format-scoring-index.json"
    policy_path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "snapshot_date": "20260601",
                # Only release 1 (master 901) is allowed -- every other
                # master's main release is excluded from the shortlist.
                "allowed_release_ids": [1],
            }
        )
    )
    candidates = rank_album_candidates(dataset_root, release_format_policy=policy_path)
    assert {c["master_id"] for c in candidates} == {901}


def test_rank_album_candidates_rejects_wrong_policy_kind(
    dataset_root: Path, tmp_path: Path
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({"kind": "release-format-policy"}))
    with pytest.raises(ValueError, match="release-format-scoring-index"):
        rank_album_candidates(dataset_root, release_format_policy=policy_path)


def test_assemble_album_catalog_editorial_always_wins_and_fills_with_candidates(
    dataset_root: Path,
) -> None:
    editorial = [{"artist": "Alice", "title": "First Light"}]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(graph, editorial, candidates, target_count=3)

    assert catalog["editorial_count"] == 1
    assert catalog["candidate_count_added"] == 2
    albums = catalog["albums"]
    assert albums[0] == {"artist": "Alice", "title": "First Light"}
    # Master 904 also resolves to Alice (artist_id 100) -- excluded as a
    # candidate even though it scores higher than masters 903/906, since the
    # editorial entry already covers that artist.
    added_artists = {a["artist"] for a in albums[1:]}
    assert "Alice" not in added_artists
    assert added_artists == {"Cara", "Dan"}
    assert len(albums) == 3


def test_assemble_album_catalog_never_pads_past_available_candidates(dataset_root: Path) -> None:
    editorial = [{"artist": "Alice", "title": "First Light"}]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(graph, editorial, candidates, target_count=100)

    # Only 2 non-Alice artists exist among the ranked candidates (Cara, Dan) --
    # can't reach 100 no matter the target, and must not fabricate entries.
    assert len(catalog["albums"]) == 3
    assert catalog["candidate_count_added"] == 2


def test_assemble_album_catalog_private_weight_can_reorder_ties(dataset_root: Path) -> None:
    editorial = [{"artist": "Alice", "title": "First Light"}]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        unweighted = assemble_album_catalog(graph, editorial, candidates, target_count=2)

        def favor_dan(artist_id: int) -> float:
            return 10.0 if artist_id == 400 else 0.0

        weighted = assemble_album_catalog(
            graph, editorial, candidates, target_count=2, private_weight_fn=favor_dan
        )

    # Cara (300) and Dan (400) tie at score 4 -- master_id tie-break picks
    # Cara unweighted, but a private weight favoring Dan's artist_id flips it.
    assert unweighted["albums"][1]["artist"] == "Cara"
    assert weighted["albums"][1]["artist"] == "Dan"


def test_assemble_album_catalog_rejects_non_positive_target(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        with pytest.raises(ValueError, match="target_count must be positive"):
            assemble_album_catalog(graph, [], [], target_count=0)
