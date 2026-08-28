from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_graph_core.analysis import (
    _catalog_version,
    assemble_album_catalog,
    exploration_corpus_version,
    rank_album_candidates,
)
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
    # ID-resolved, not a re-queryable name pair (see ADR 0038 / the collision
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


@pytest.mark.parametrize("target_count", [500, 1000])
def test_assemble_album_catalog_at_exploration_tier_scale_still_never_pads(
    dataset_root: Path, target_count: int
) -> None:
    """Fixture-scale stand-in for Slice D's 500/1000-album exploration tiers
    (docs/EXPLORATION_TIER_COMPARISON.md, ADR 0049) -- proves the existing
    ranking/assembly pipeline is already parametric at these target counts
    without requiring the private one-hop dataset in CI."""
    editorial = [{"artist": "Alice", "title": "First Light"}]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(graph, editorial, candidates, target_count=target_count)

    assert catalog["target_count"] == target_count
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


def _pre_resolved(
    master_id: int | None,
    main_release_id: int,
    artist_id: int,
    artist: str,
    title: str,
    year: int = 2000,
) -> dict:
    return {
        "query_artist": artist,
        "query_title": title,
        "master_id": master_id,
        "main_release_id": main_release_id,
        "artist_id": artist_id,
        "artist": artist,
        "title": title,
        "year": year,
    }


def test_pre_resolved_allows_multiple_albums_by_the_same_artist(dataset_root: Path) -> None:
    """The exact bug ADR 0065 recorded before any code existed to cause it:
    a personal-lane artist with several albums (five Jamiroquai albums in
    the real Phase 7 slate) must NOT be silently reduced to one by a
    per-artist dedup. Three fabricated albums, all artist_id=700, none of
    which need to exist in the fixture graph -- pre-resolved entries carry
    their own identity and are never re-resolved by text search."""
    pre_resolved = [
        _pre_resolved(9001, 9001, 700, "Fictoquai", "Album One"),
        _pre_resolved(9002, 9002, 700, "Fictoquai", "Album Two"),
        _pre_resolved(9003, 9003, 700, "Fictoquai", "Album Three"),
    ]
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph, [], [], target_count=10, pre_resolved_albums=pre_resolved
        )
    assert catalog["pre_resolved_count"] == 3
    assert catalog["pre_resolved_missed"] == []
    fictoquai_albums = [a for a in catalog["albums"] if a["artist"] == "Fictoquai"]
    assert len(fictoquai_albums) == 3
    assert {a["title"] for a in fictoquai_albums} == {"Album One", "Album Two", "Album Three"}


def test_pre_resolved_excludes_a_ranked_candidate_by_the_same_artist(dataset_root: Path) -> None:
    """Master 904 resolves to artist_id 100 (Alice) in the shared fixture --
    once Alice is covered by a pre-resolved (Bucket A) entry, a ranked
    candidate by the same artist must not ALSO take a graph-rich slot."""
    pre_resolved = [_pre_resolved(9001, 9001, 100, "Alice", "Pre-Resolved Alice Album")]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(
            graph, [], candidates, target_count=10, pre_resolved_albums=pre_resolved
        )
    added_via_candidates = {
        a["artist"] for a in catalog["albums"] if a["title"] != "Pre-Resolved Alice Album"
    }
    assert "Alice" not in added_via_candidates
    assert catalog["candidate_count_added"] == 2  # Cara, Dan -- not Alice's master 904


def test_pre_resolved_deduplicates_against_editorial_by_master_id(dataset_root: Path) -> None:
    editorial = [{"artist": "Alice", "title": "First Light"}]  # resolves to master 901
    pre_resolved = [_pre_resolved(901, 1, 999, "Someone Else", "Duplicate Of Editorial")]
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph, editorial, [], target_count=10, pre_resolved_albums=pre_resolved
        )
    assert catalog["pre_resolved_count"] == 0
    assert len(catalog["pre_resolved_missed"]) == 1
    assert "duplicate master_id" in catalog["pre_resolved_missed"][0]["reason"]


def test_pre_resolved_deduplicates_against_itself_by_master_id(dataset_root: Path) -> None:
    pre_resolved = [
        _pre_resolved(9001, 9001, 700, "Fictoquai", "First Copy"),
        _pre_resolved(9001, 9001, 701, "Someone Else", "Duplicate Master"),
    ]
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph, [], [], target_count=10, pre_resolved_albums=pre_resolved
        )
    assert catalog["pre_resolved_count"] == 1
    assert catalog["albums"][0]["title"] == "First Copy"
    assert len(catalog["pre_resolved_missed"]) == 1
    assert "duplicate master_id" in catalog["pre_resolved_missed"][0]["reason"]


def test_pre_resolved_missed_never_leaks_a_field_outside_the_seed_contract(
    dataset_root: Path,
) -> None:
    """Real gap found in review: `pre_resolved_missed` is published verbatim
    inside the committed, public catalog artifact. An out-of-contract field
    on a REJECTED entry (a stray private note, or worse) must never ride
    along -- only the documented editorial-seed-v1.json fields plus
    `reason` are ever serialized here, regardless of what the input dict
    happens to carry."""
    entry = _pre_resolved(9001, 9001, 700, "Fictoquai", "Not Allowed")
    entry["private_note"] = "should never appear in the public catalog"
    entry["reviewer_email"] = "leak@example.invalid"
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph,
            [],
            [],
            target_count=10,
            pre_resolved_albums=[entry],
            allowed_release_ids=frozenset({1, 2, 3}),  # 9001 not included -- rejected
        )
    assert catalog["pre_resolved_count"] == 0
    missed = catalog["pre_resolved_missed"][0]
    assert "private_note" not in missed
    assert "reviewer_email" not in missed
    assert set(missed.keys()) == {
        "query_artist",
        "query_title",
        "master_id",
        "main_release_id",
        "artist_id",
        "artist",
        "title",
        "year",
        "reason",
    }


def test_pre_resolved_respects_allowed_release_ids(dataset_root: Path) -> None:
    pre_resolved = [_pre_resolved(9001, 9001, 700, "Fictoquai", "Not Allowed")]
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph,
            [],
            [],
            target_count=10,
            pre_resolved_albums=pre_resolved,
            allowed_release_ids=frozenset({1, 2, 3}),  # 9001 not included
        )
    assert catalog["pre_resolved_count"] == 0
    assert "allow-list" in catalog["pre_resolved_missed"][0]["reason"]


def test_pre_resolved_respects_master_exclusions(dataset_root: Path) -> None:
    pre_resolved = [_pre_resolved(9001, 9001, 700, "Fictoquai", "Excluded Master")]
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph,
            [],
            [],
            target_count=10,
            pre_resolved_albums=pre_resolved,
            master_exclusions=frozenset({9001}),
        )
    assert catalog["pre_resolved_count"] == 0
    assert "exclusions" in catalog["pre_resolved_missed"][0]["reason"]


def test_pre_resolved_respects_non_studio_genre_when_masters_attached(
    dataset_root: Path, masters_root: Path
) -> None:
    """Master 901 IS in the masters fixture but with empty genres/styles
    (see conftest.py's FIXTURE_MASTERS) -- confirm a pre-resolved entry
    pointed at it still passes (no false positive), proving this path is
    genuinely wired to the same real policy check, not a stub."""
    pre_resolved = [_pre_resolved(901, 1, 999, "Someone Else", "Reuses Master 901 Deliberately")]
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        catalog = assemble_album_catalog(
            graph, [], [], target_count=10, pre_resolved_albums=pre_resolved
        )
    assert catalog["pre_resolved_count"] == 1
    # Masters attached: title/year come from the master, not the query --
    # same override behavior match_albums's own editorial path already has.
    assert catalog["albums"][0]["title"] == "First Light (Deluxe)"
    assert catalog["albums"][0]["year"] == 1995


def test_pre_resolved_counts_toward_target(dataset_root: Path) -> None:
    pre_resolved = [_pre_resolved(9001, 9001, 700, "Fictoquai", "One Album")]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(
            graph, [], candidates, target_count=2, pre_resolved_albums=pre_resolved
        )
    assert catalog["pre_resolved_count"] == 1
    assert catalog["candidate_count_added"] == 1
    assert len(catalog["albums"]) == 2


def test_a_candidate_sharing_a_pre_resolved_master_id_is_excluded_even_with_a_different_artist(
    dataset_root: Path,
) -> None:
    """Defensive edge case: a ranked candidate whose master_id coincidentally
    matches a pre-resolved entry's master_id must never be double-added,
    even if the candidate's own artist_id label differs (which should not
    happen with real Discogs data, but the guard costs two lines)."""
    pre_resolved = [_pre_resolved(903, 3, 999, "Someone Else", "Claims Master 903")]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(
            graph, [], candidates, target_count=10, pre_resolved_albums=pre_resolved
        )
    master_ids_in_catalog = [a["master_id"] for a in catalog["albums"] if a["master_id"] == 903]
    assert len(master_ids_in_catalog) == 1  # not duplicated


def test_no_pre_resolved_albums_is_fully_backward_compatible(dataset_root: Path) -> None:
    editorial = [{"artist": "Alice", "title": "First Light"}]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(graph, editorial, candidates, target_count=3)
    assert catalog["pre_resolved_count"] == 0
    assert catalog["pre_resolved_missed"] == []
    assert catalog["pre_resolved_buckets"] == []
    assert len(catalog["albums"]) == 3


def test_additional_pre_resolved_labels_each_bucket_separately(dataset_root: Path) -> None:
    """Phase 7 Buckets B/C: distinct labeled lanes, each counted and
    reported separately in `pre_resolved_buckets` -- this is what lets
    catalog_audit.py tell a graph-rich pick apart from a coverage-gap pick
    instead of collapsing every pre-resolved album into one label."""
    personal = [_pre_resolved(9001, 9001, 700, "Fictoquai", "Bucket A Pick")]
    graph_rich = [_pre_resolved(7501, 7501, 750, "Graph Rich Artist", "Bucket B Pick")]
    coverage_gap = [_pre_resolved(7601, 7601, 760, "Coverage Gap Artist", "Bucket C Pick")]
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph,
            [],
            [],
            target_count=10,
            pre_resolved_albums=personal,
            additional_pre_resolved=[("graph_rich", graph_rich), ("coverage_gap", coverage_gap)],
        )
    assert catalog["pre_resolved_count"] == 3
    assert catalog["pre_resolved_buckets"] == [
        {"label": "personal_editorial", "count": 1},
        {"label": "graph_rich", "count": 1},
        {"label": "coverage_gap", "count": 1},
    ]
    titles = {a["title"] for a in catalog["albums"]}
    assert titles == {"Bucket A Pick", "Bucket B Pick", "Bucket C Pick"}


def test_additional_pre_resolved_dedups_against_earlier_groups_by_master_id(
    dataset_root: Path,
) -> None:
    """A later group's entry sharing an earlier group's master_id is
    dropped and reported in `pre_resolved_missed`, never double-included --
    the same cross-bucket collision guard `pre_resolved_albums` already
    applies to editorial, extended across every additional lane too."""
    personal = [_pre_resolved(9001, 9001, 700, "Fictoquai", "First Claim")]
    graph_rich = [_pre_resolved(9001, 9001, 750, "Someone Else", "Duplicate Master")]
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph,
            [],
            [],
            target_count=10,
            pre_resolved_albums=personal,
            additional_pre_resolved=[("graph_rich", graph_rich)],
        )
    assert catalog["pre_resolved_count"] == 1
    assert catalog["pre_resolved_buckets"] == [
        {"label": "personal_editorial", "count": 1},
        {"label": "graph_rich", "count": 0},
    ]
    assert len(catalog["pre_resolved_missed"]) == 1
    assert "duplicate master_id" in catalog["pre_resolved_missed"][0]["reason"]


def test_additional_pre_resolved_excludes_a_ranked_candidate_by_the_same_artist(
    dataset_root: Path,
) -> None:
    """The same artist-exclusion rule `pre_resolved_albums` applies to
    candidates must also apply to `additional_pre_resolved` entries -- an
    artist covered by a graph-rich pick doesn't ALSO need a generic
    candidate slot."""
    graph_rich = [_pre_resolved(9001, 9001, 100, "Alice", "Graph Rich Alice Album")]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(
            graph,
            [],
            candidates,
            target_count=10,
            additional_pre_resolved=[("graph_rich", graph_rich)],
        )
    added_via_candidates = {
        a["artist"] for a in catalog["albums"] if a["title"] != "Graph Rich Alice Album"
    }
    assert "Alice" not in added_via_candidates


def test_additional_pre_resolved_alone_is_labeled_without_a_personal_editorial_entry(
    dataset_root: Path,
) -> None:
    """No phantom "personal_editorial: 0" bucket when --personal-seed was
    never given at all -- only lanes that actually ran appear."""
    graph_rich = [_pre_resolved(9001, 9001, 750, "Graph Rich Artist", "Only Bucket B Pick")]
    with CreditGraph.open(dataset_root) as graph:
        catalog = assemble_album_catalog(
            graph, [], [], target_count=10, additional_pre_resolved=[("graph_rich", graph_rich)]
        )
    assert catalog["pre_resolved_buckets"] == [{"label": "graph_rich", "count": 1}]


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


def test_rank_album_candidates_excludes_already_published_masters(dataset_root: Path) -> None:
    """Master 901 (release 1, "First Light") would otherwise rank -- confirm
    it's present unfiltered, then confirm excluding it removes it and nothing
    else, without shifting any other candidate's score."""
    unfiltered = rank_album_candidates(dataset_root)
    assert 901 in {c["master_id"] for c in unfiltered}

    filtered = rank_album_candidates(dataset_root, already_published_master_ids=frozenset({901}))
    filtered_ids = {c["master_id"] for c in filtered}
    assert 901 not in filtered_ids
    assert filtered_ids == {c["master_id"] for c in unfiltered} - {901}

    unfiltered_by_id = {c["master_id"]: c for c in unfiltered}
    for c in filtered:
        assert c == unfiltered_by_id[c["master_id"]]


def test_rank_album_candidates_already_published_composes_with_curated_exclusions(
    dataset_root: Path,
) -> None:
    """Both exclusion mechanisms narrow the same WHERE clause -- confirm they
    stack rather than one silently overriding the other."""
    candidates = rank_album_candidates(
        dataset_root,
        already_published_master_ids=frozenset({901}),
        master_exclusions=frozenset({903}),
    )
    ids = {c["master_id"] for c in candidates}
    assert 901 not in ids
    assert 903 not in ids


def test_rank_album_candidates_empty_already_published_set_excludes_nothing(
    dataset_root: Path,
) -> None:
    with_empty = rank_album_candidates(dataset_root, already_published_master_ids=frozenset())
    without = rank_album_candidates(dataset_root)
    assert {c["master_id"] for c in with_empty} == {c["master_id"] for c in without}


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


def test_exploration_corpus_version_uses_a_distinct_prefix_from_catalog_version(
    dataset_root: Path,
) -> None:
    """ADR 0049: an exploration tier's version must never collide with, or be
    mistakable for, the real editorial catalog's catalog_version -- same
    fingerprint shape, deliberately different prefix."""
    editorial = [{"artist": "Alice", "title": "First Light"}]
    with CreditGraph.open(dataset_root) as graph:
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(graph, editorial, candidates, target_count=500)

    albums = catalog["albums"]
    snapshot_date = "20260601"
    explore_version = exploration_corpus_version(albums, snapshot_date)
    catalog_version = _catalog_version(albums, snapshot_date)

    assert explore_version.startswith(f"explore-v1-{snapshot_date}-")
    assert catalog_version.startswith(f"catalog-v1-{snapshot_date}-")
    assert explore_version != catalog_version
    # The two share the same digest (same album set), only the prefix differs.
    assert explore_version.rsplit("-", 1)[-1] == catalog_version.rsplit("-", 1)[-1]


def test_exploration_corpus_version_is_deterministic() -> None:
    albums = [
        {"artist_id": 1, "main_release_id": 10, "master_id": 100, "year": 1990},
        {"artist_id": 2, "main_release_id": 20, "master_id": 200, "year": 2000},
    ]
    assert exploration_corpus_version(albums, "20260601") == exploration_corpus_version(
        list(reversed(albums)), "20260601"
    )
