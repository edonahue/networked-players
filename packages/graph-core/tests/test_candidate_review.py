from __future__ import annotations

from pathlib import Path

from networked_players_graph_core.analysis import rank_album_candidates
from networked_players_graph_core.candidate_review import review_album_candidates
from networked_players_graph_core.graph import CreditGraph


def test_review_decorates_every_candidate_without_dropping_or_reordering_the_set(
    dataset_root: Path,
) -> None:
    candidates = rank_album_candidates(dataset_root)
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        report = review_album_candidates(graph, candidates, published_graph_artist_ids=frozenset())

    assert report["candidate_count"] == len(candidates)
    reviewed_master_ids = {c["master_id"] for c in report["candidates"]}
    assert reviewed_master_ids == {c["master_id"] for c in candidates}
    # Every original field survives the decoration untouched.
    original_by_master = {c["master_id"]: c for c in candidates}
    for reviewed in report["candidates"]:
        original = original_by_master[reviewed["master_id"]]
        for key, value in original.items():
            assert reviewed[key] == value


def test_review_counts_new_contributors_against_the_published_graph(dataset_root: Path) -> None:
    candidates = rank_album_candidates(dataset_root)
    # Master 901 = release 1 = Alice(100) + Bob(200).
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        report = review_album_candidates(
            graph, candidates, published_graph_artist_ids=frozenset({100})
        )

    by_master = {c["master_id"]: c for c in report["candidates"]}
    assert by_master[901]["contributor_count"] == 2
    assert by_master[901]["new_contributor_count"] == 1
    assert "1 not already present" in by_master[901]["why"]


def test_review_treats_nothing_published_as_every_contributor_new(dataset_root: Path) -> None:
    candidates = rank_album_candidates(dataset_root)
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        report = review_album_candidates(graph, candidates, published_graph_artist_ids=frozenset())

    for reviewed in report["candidates"]:
        assert reviewed["new_contributor_count"] == reviewed["contributor_count"]


def test_review_sorts_by_new_contributor_count_then_score_then_master_id(
    dataset_root: Path,
) -> None:
    candidates = rank_album_candidates(dataset_root)
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        report = review_album_candidates(graph, candidates, published_graph_artist_ids=frozenset())

    keys = [
        (-c["new_contributor_count"], -c["score"], c["master_id"]) for c in report["candidates"]
    ]
    assert keys == sorted(keys)


def test_review_surfaces_format_descriptor_caveats_on_the_candidates_own_release(
    tmp_path: Path,
) -> None:
    """A candidate's evidence quality is judged on ITS OWN main release's
    format tags -- reusing the same caveat vocabulary the evidence release
    registry already publishes (ADR 0058), never a positive claim when no
    tag is present (release 3 below stays an empty list, not "clean")."""
    from conftest import write_synthetic_dataset

    def _release(release_id: int, title: str, master_id: int) -> dict[str, object]:
        return {
            "snapshot_date": "20260601",
            "release_id": release_id,
            "status": "Accepted",
            "title": title,
            "country": None,
            "released": "1995",
            "master_id": master_id,
            "master_is_main_release": True,
            "data_quality": None,
            "source_url": f"https://example.invalid/release/{release_id}",
        }

    def _performed(release_id: int, *, artist_id: int, name: str) -> list[dict[str, object]]:
        return [
            {
                "snapshot_date": "20260601",
                "release_id": release_id,
                "track_index": None,
                "track_path": None,
                "track_position": None,
                "track_title": None,
                "credit_scope": "release_artist",
                "artist_id": artist_id,
                "name": name,
                "anv": None,
                "join_text": None,
                "role_text": "Performer",
                "credited_tracks_text": None,
                "is_linked": True,
                "playable_identity": True,
            },
            {
                "snapshot_date": "20260601",
                "release_id": release_id,
                "track_index": 0,
                "track_path": "0",
                "track_position": "1",
                "track_title": "Track 1",
                "credit_scope": "track_artist",
                "artist_id": artist_id,
                "name": name,
                "anv": None,
                "join_text": None,
                "role_text": None,
                "credited_tracks_text": None,
                "is_linked": True,
                "playable_identity": True,
            },
        ]

    releases = [
        _release(1, "Tagged Compilation", master_id=901),
        _release(3, "A Real Album", master_id=903),
    ]
    credits = [
        *_performed(1, artist_id=100, name="Alice"),
        *_performed(1, artist_id=200, name="Bob"),
        *_performed(3, artist_id=300, name="Cara"),
        *_performed(3, artist_id=400, name="Dan"),
    ]
    release_format_rows = [
        {
            "snapshot_date": "20260601",
            "release_id": 1,
            "format_index": 0,
            "format_name": "CD",
            "quantity": 1,
            "format_text": None,
            "descriptions": ["Compilation"],
        },
    ]
    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601",
        release_rows=releases,
        credit_rows=credits,
        release_format_rows=release_format_rows,
    )

    candidates = rank_album_candidates(root)
    with CreditGraph.open(root, build_edges=False) as graph:
        report = review_album_candidates(graph, candidates, published_graph_artist_ids=frozenset())

    by_master = {c["master_id"]: c for c in report["candidates"]}
    assert by_master[901]["evidence_caveats"] == ["compilation"]
    assert "tagged: compilation" in by_master[901]["why"]
    assert by_master[903]["evidence_caveats"] == []


def test_review_never_promotes_a_candidate_to_any_catalog(dataset_root: Path) -> None:
    """A structural/documentation guard, not a behavioral one: this report
    has no write path to any catalog artifact, only a `candidates` list and
    a `method_note` explaining its own limits."""
    candidates = rank_album_candidates(dataset_root)
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        report = review_album_candidates(graph, candidates, published_graph_artist_ids=frozenset())

    assert set(report.keys()) == {"version", "method_note", "candidate_count", "candidates"}
