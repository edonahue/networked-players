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
    # ID-resolved, not a re-queryable name pair (see ADR 0037 / the collision
    # risk a name-based re-match would reopen).
    assert albums[0]["artist_id"] == 100
    assert albums[0]["artist"] == "Alice"
    assert albums[0]["title"] == "First Light"
    assert albums[0]["main_release_id"] == 1
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


def test_assemble_album_catalog_applies_release_format_policy_to_editorial(
    dataset_root: Path,
) -> None:
    editorial = [{"artist": "Alice", "title": "First Light"}]  # release 1
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(
            graph,
            editorial,
            candidates,
            target_count=3,
            allowed_release_ids=frozenset({2, 3, 4, 5, 6, 7}),  # release 1 excluded
        )

    assert catalog["editorial_count"] == 0
    # Master 904 (also Alice, artist_id 100) is now a free candidate slot
    # since the editorial entry no longer consumes that artist_id.
    added_artists = {a["artist"] for a in catalog["albums"]}
    assert "Alice" in added_artists


def test_assemble_album_catalog_rejects_non_positive_target(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        with pytest.raises(ValueError, match="target_count must be positive"):
            assemble_album_catalog(graph, [], [], target_count=0)


def test_assemble_album_catalog_resolves_candidates_by_id_not_name(tmp_path: Path) -> None:
    """Two real, unrelated Discogs artists can share a display name (exactly
    why Discogs itself disambiguates with numeric IDs). A candidate resolved
    to a specific artist_id must stay pinned to that artist_id all the way
    through -- never re-matched by name, which could silently resolve to the
    wrong same-named artist."""
    from conftest import write_synthetic_dataset

    def _release(release_id: int, title: str) -> dict[str, object]:
        return {
            "snapshot_date": "20260601",
            "release_id": release_id,
            "status": "Accepted",
            "title": title,
            "country": None,
            "released": "1995",
            "master_id": None,
            "master_is_main_release": None,
            "data_quality": None,
            "source_url": f"https://example.invalid/release/{release_id}",
        }

    def _credit(
        release_id: int,
        *,
        artist_id: int,
        name: str,
        scope: str,
        track_index: int | None = None,
    ) -> dict[str, object]:
        return {
            "snapshot_date": "20260601",
            "release_id": release_id,
            "track_index": track_index,
            "track_path": None if track_index is None else str(track_index),
            "track_position": None if track_index is None else str(track_index + 1),
            "track_title": None if track_index is None else f"Track {track_index + 1}",
            "credit_scope": scope,
            "artist_id": artist_id,
            "name": name,
            "anv": None,
            "join_text": None,
            "role_text": "Performer",
            "credited_tracks_text": None,
            "is_linked": True,
            "playable_identity": True,
        }

    # Artist 100 "Sam" is co-billed with Bob(200) on release 1 -- this is the
    # real candidate. Artist 999 is a completely unrelated person who also
    # happens to be named "Sam", billed alone on release 9.
    releases = [_release(1, "Solo A"), _release(9, "Totally Different Album")]
    credits = [
        _credit(1, artist_id=100, name="Sam", scope="release_artist"),
        _credit(1, artist_id=100, name="Sam", scope="track_artist", track_index=0),
        _credit(1, artist_id=200, name="Bob", scope="release_artist"),
        _credit(1, artist_id=200, name="Bob", scope="track_artist", track_index=0),
        _credit(9, artist_id=999, name="Sam", scope="release_artist"),
        _credit(9, artist_id=999, name="Sam", scope="track_artist", track_index=0),
    ]
    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=releases, credit_rows=credits
    )

    editorial = [{"artist": "Bob", "title": "Solo A"}]
    candidates = [
        {
            "master_id": None,
            "sample_title": "Solo A",
            "variant_count": 1,
            "credit_rows": 4,
            "score": 4,
            "main_release_id": 1,
            "artist_id": 100,
            "artist_name": "Sam",
            "year": 1995,
        }
    ]

    with CreditGraph.open(root) as graph:
        catalog = assemble_album_catalog(graph, editorial, candidates, target_count=2)

    sam_entries = [a for a in catalog["albums"] if a["artist"] == "Sam"]
    assert len(sam_entries) == 1
    assert sam_entries[0]["artist_id"] == 100  # never 999, despite the shared name
    assert sam_entries[0]["main_release_id"] == 1


def test_rank_album_candidates_excludes_placeholder_artists(tmp_path: Path) -> None:
    """Real bug found in a real generation run: a compilation billed to
    artist 194 ("Various Artists" -- see placeholder_artists.json / ADR 0035)
    surfaced as a graph-rich candidate because its main release happened to
    carry an explicit Album format descriptor. Excluded by numeric artist_id,
    the same guard credit_edges_sql already applies -- never by name."""
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

    def _credit(release_id: int, *, artist_id: int, name: str) -> list[dict[str, object]]:
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
        _release(1, "A Real Album", master_id=901),
        _release(2, "Two Rooms - A Tribute Compilation", master_id=902),
    ]
    credits = [
        *_credit(1, artist_id=100, name="Alice"),
        *_credit(2, artist_id=194, name="Various"),
    ]
    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=releases, credit_rows=credits
    )

    candidates = rank_album_candidates(root)
    assert {c["artist_id"] for c in candidates} == {100}
    assert 194 not in {c["artist_id"] for c in candidates}
