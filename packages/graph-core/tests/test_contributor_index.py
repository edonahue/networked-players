from __future__ import annotations

from typing import Any

from networked_players_graph_core.contributor_index import (
    build_album_hop_distances,
    build_background_only_profiles,
    build_contributor_index,
)
from networked_players_graph_core.role_taxonomy import RoleCategory

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _catalog() -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist_id": 100, "year": 1995},
            {"id": "master-2", "title": "Second Wave", "artist_id": 200, "year": 2001},
            {"id": "master-3", "title": "Third Decoy", "artist_id": 300, "year": 1988},
        ],
    }


def _challenge_release(release_id: int, credits: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "title": f"R{release_id}",
        "credits": credits,
    }


def _credit(artist_id: int, role_text: str) -> dict[str, Any]:
    return {
        "release_id": None,
        "credit_scope": "release_artist",
        "artist_id": artist_id,
        "name": f"Artist {artist_id}",
        "anv": None,
        "role_text": role_text,
        "is_linked": True,
        "playable_identity": True,
    }


def _challenge() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [
            {"artist_id": 100, "name": "Alice"},
            {"artist_id": 200, "name": "Bob"},
        ],
        "paths": [
            {
                "id": "path-1",
                "from_album_id": "master-1",
                "to_album_id": "master-2",
                "hops": [{"release_id": 501, "artist_a_id": 100, "artist_b_id": 200}],
            }
        ],
        "releases": [
            _challenge_release(501, [_credit(100, "Guitar"), _credit(200, "Bass")]),
        ],
    }


def _evidence_release_registry() -> dict[str, Any]:
    # Deliberately different decades than the connected catalog albums
    # (master-1=1995, master-2=2001, master-3=1988) -- this is the whole
    # point of the fixture: decade_activity must key off these real
    # per-release years, not the catalog album's own year. Only the two
    # fields build_contributor_index actually reads are populated; a real
    # registry carries more (titles, countries, ...), irrelevant here.
    return {"release_ids": [501, 900], "years": [1979, 2015]}


def _routes_universe() -> dict[str, Any]:
    return {"provenance": {"catalog_version": _CATALOG_VERSION}, "albums": []}


def _routes_rounds() -> dict[str, Any]:
    return {
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [
            {"artist_id": 200, "name": "Bob"},
            {"artist_id": 300, "name": "Carol"},
        ],
        "rounds": [
            {
                "from_album_id": "master-2",
                "to_album_id": "master-3",
                "hops": [
                    {
                        "release_id": 900,
                        "artist_a_id": 200,
                        "artist_b_id": 300,
                        "role_a": "Producer",
                        "role_b": "Mastered By",
                    }
                ],
            }
        ],
        "releases": [],
    }


def _build() -> dict[str, Any]:
    return build_contributor_index(
        challenge=_challenge(),
        routes_universe=_routes_universe(),
        routes_rounds=_routes_rounds(),
        catalog=_catalog(),
        evidence_release_registry=_evidence_release_registry(),
        generated_at="2026-08-03T00:00:00+00:00",
    )


def test_top_level_shape() -> None:
    index = _build()
    assert index["schema_version"] == 1
    assert index["catalog_version"] == _CATALOG_VERSION
    assert index["contributor_index_version"].startswith(f"contributor-index-v1-{_SNAPSHOT}-")
    assert index["generated_at"] == "2026-08-03T00:00:00+00:00"


def test_every_hop_artist_becomes_a_contributor() -> None:
    index = _build()
    ids = {c["artist_id"] for c in index["contributors"]}
    assert ids == {100, 200, 300}


def test_role_text_from_challenge_credit_rows_is_attached() -> None:
    index = _build()
    alice = next(c for c in index["contributors"] if c["artist_id"] == 100)
    assert "Guitar" in alice["role_text_examples"]
    assert RoleCategory.STRINGS.value in alice["role_categories"]


def test_role_text_from_routes_hop_fields_is_attached() -> None:
    index = _build()
    carol = next(c for c in index["contributors"] if c["artist_id"] == 300)
    assert "Mastered By" in carol["role_text_examples"]
    assert RoleCategory.ENGINEERING.value in carol["role_categories"]


def test_albums_are_the_endpoints_of_every_path_or_round_the_contributor_appears_in() -> None:
    index = _build()
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["albums"] == ["master-1", "master-2", "master-3"]


def _hop_distance_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Mirrors the real Jamiroquai/Pink-Floyd shape (artist -- bridge
    engineer -- artist), scaled down: a 2-hop path where the middle artist
    is genuinely 1 hop from BOTH endpoints, never 0."""
    catalog = {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-endpoint-a", "title": "A", "artist_id": 1, "year": 1995},
            {"id": "master-endpoint-b", "title": "B", "artist_id": 3, "year": 1996},
        ],
    }
    challenge = {
        "schema_version": 2,
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [
            {"artist_id": 1, "name": "Endpoint Artist"},
            {"artist_id": 2, "name": "Bridge Engineer"},
            {"artist_id": 3, "name": "Other Endpoint Artist"},
        ],
        "paths": [
            {
                "id": "path-1",
                "from_album_id": "master-endpoint-a",
                "to_album_id": "master-endpoint-b",
                "hops": [
                    {"release_id": 1, "artist_a_id": 1, "artist_b_id": 2},
                    {"release_id": 2, "artist_a_id": 2, "artist_b_id": 3},
                ],
            }
        ],
        "releases": [],
    }
    routes_rounds = {
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [],
        "rounds": [],
        "releases": [],
    }
    return catalog, challenge, routes_rounds


def test_build_album_hop_distances_top_level_shape() -> None:
    catalog, challenge, routes_rounds = _hop_distance_fixture()
    result = build_album_hop_distances(
        challenge=challenge,
        routes_rounds=routes_rounds,
        catalog=catalog,
        generated_at="2026-08-03T00:00:00+00:00",
    )
    assert result["schema_version"] == 1
    assert result["catalog_version"] == _CATALOG_VERSION
    assert result["album_hop_distances_version"].startswith(f"album-hop-distances-v1-{_SNAPSHOT}-")
    assert result["generated_at"] == "2026-08-03T00:00:00+00:00"


def test_hop_distance_reflects_position_in_a_multi_hop_path() -> None:
    """A regression guard for the real bug this addendum fixed: a contributor
    two hops from an endpoint used to be attributed to that endpoint
    identically to one directly adjacent to it."""
    catalog, challenge, routes_rounds = _hop_distance_fixture()
    result = build_album_hop_distances(
        challenge=challenge,
        routes_rounds=routes_rounds,
        catalog=catalog,
        generated_at="2026-08-03T00:00:00+00:00",
    )
    by_artist: dict[int, list[dict[str, Any]]] = {}
    for entry in result["entries"]:
        by_artist.setdefault(entry["artist_id"], []).append(
            {"album_id": entry["album_id"], "hop_distance": entry["hop_distance"]}
        )

    # The endpoint-adjacent artist is 0 hops from their own endpoint, 2 hops
    # from the far one.
    assert by_artist[1] == [
        {"album_id": "master-endpoint-a", "hop_distance": 0},
        {"album_id": "master-endpoint-b", "hop_distance": 2},
    ]
    assert by_artist[3] == [
        {"album_id": "master-endpoint-b", "hop_distance": 0},
        {"album_id": "master-endpoint-a", "hop_distance": 2},
    ]
    # The middle bridge artist is 1 hop from BOTH endpoints -- never 0, even
    # though contributor_index's own `albums[]` (the plain id list) treats
    # every hop participant as equally present. This is exactly why
    # album_hop_distances exists as a companion artifact.
    assert by_artist[2] == [
        {"album_id": "master-endpoint-a", "hop_distance": 1},
        {"album_id": "master-endpoint-b", "hop_distance": 1},
    ]


def test_build_album_hop_distances_deterministic_across_repeated_builds() -> None:
    catalog, challenge, routes_rounds = _hop_distance_fixture()

    def _run() -> dict[str, Any]:
        return build_album_hop_distances(
            challenge=challenge,
            routes_rounds=routes_rounds,
            catalog=catalog,
            generated_at="2026-08-03T00:00:00+00:00",
        )

    assert _run() == _run()


def test_build_album_hop_distances_mismatched_catalog_version_raises() -> None:
    import pytest

    catalog, challenge, routes_rounds = _hop_distance_fixture()
    challenge["provenance"]["catalog_version"] = "catalog-v1-wrong"
    with pytest.raises(ValueError, match="catalog_version"):
        build_album_hop_distances(
            challenge=challenge,
            routes_rounds=routes_rounds,
            catalog=catalog,
            generated_at="2026-08-03T00:00:00+00:00",
        )


def _background_only_profiles_build() -> dict[str, Any]:
    return build_background_only_profiles(
        challenge=_challenge(),
        routes_rounds=_routes_rounds(),
        catalog=_catalog(),
        generated_at="2026-08-31T00:00:00+00:00",
    )


def test_build_background_only_profiles_top_level_shape() -> None:
    result = _background_only_profiles_build()
    assert result["schema_version"] == 1
    assert result["catalog_version"] == _CATALOG_VERSION
    assert result["background_only_profiles_version"].startswith(
        f"background-only-profiles-v1-{_SNAPSHOT}-"
    )
    assert result["generated_at"] == "2026-08-31T00:00:00+00:00"


def test_background_only_profiles_flags_only_the_pure_mastering_credit() -> None:
    """Using the main fixture: Alice (100) is credited only "Guitar" (no
    engineering at all -- nothing to background), Bob (200) is credited
    "Bass" and "Producer" (real substantive work), Carol (300) is credited
    ONLY "Mastered By" -- background-only."""
    result = _background_only_profiles_build()
    assert result["artist_ids"] == [300]


def test_background_only_profiles_artist_ids_sorted_with_no_duplicates() -> None:
    catalog = {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-a", "title": "A", "artist_id": 1, "year": 1990},
            {"id": "master-b", "title": "B", "artist_id": 2, "year": 1991},
        ],
    }
    challenge = {
        "schema_version": 2,
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [{"artist_id": 1, "name": "One"}, {"artist_id": 2, "name": "Two"}],
        "paths": [
            {
                "id": "path-1",
                "from_album_id": "master-a",
                "to_album_id": "master-b",
                "hops": [{"release_id": 1, "artist_a_id": 2, "artist_b_id": 1}],
            }
        ],
        "releases": [
            _challenge_release(1, [_credit(2, "Mastered By"), _credit(1, "Recorded By")]),
        ],
    }
    routes_rounds = {
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [],
        "rounds": [],
    }
    result = build_background_only_profiles(
        challenge=challenge,
        routes_rounds=routes_rounds,
        catalog=catalog,
        generated_at="2026-08-31T00:00:00+00:00",
    )
    assert result["artist_ids"] == [1, 2]


def test_build_background_only_profiles_deterministic_across_repeated_builds() -> None:
    def _run() -> dict[str, Any]:
        return _background_only_profiles_build()

    assert _run() == _run()


def test_build_background_only_profiles_mismatched_catalog_version_raises() -> None:
    import pytest

    challenge = _challenge()
    challenge["provenance"]["catalog_version"] = "catalog-v1-wrong"
    with pytest.raises(ValueError, match="catalog_version"):
        build_background_only_profiles(
            challenge=challenge,
            routes_rounds=_routes_rounds(),
            catalog=_catalog(),
            generated_at="2026-08-31T00:00:00+00:00",
        )


def test_decade_activity_derived_from_the_contributors_own_evidence_release_years() -> None:
    # Alice is credited only via release 501 (real year 1979, per the
    # evidence-release registry fixture) -- her decade must be [1970], not
    # the connected albums' own years (master-1=1995, master-2=2001), which
    # is what the pre-Slice-8 album-year-based computation would have
    # produced ([1990, 2000]).
    index = _build()
    alice = next(c for c in index["contributors"] if c["artist_id"] == 100)
    assert alice["decade_activity"] == [1970]
    # Bob is credited via both release 501 (1979) and release 900 (2015) --
    # his real evidence spans those two decades, not the three connected
    # albums' years (1980s/1990s/2000s) the old computation would have used.
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["decade_activity"] == [1970, 2010]
    # Carol is credited only via release 900 (2015).
    carol = next(c for c in index["contributors"] if c["artist_id"] == 300)
    assert carol["decade_activity"] == [2010]


def test_connection_count_and_neighbors_reflect_published_hops_only() -> None:
    index = _build()
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["connection_count"] == 2
    assert set(bob["neighboring_contributor_ids"]) == {100, 300}


def test_evidence_entries_reference_real_release_ids() -> None:
    index = _build()
    alice = next(c for c in index["contributors"] if c["artist_id"] == 100)
    assert {"release_id": 501, "role_text": "Guitar"} in alice["evidence"]


def test_interesting_next_step_picks_a_role_disjoint_neighbor() -> None:
    # Alice (strings only) has one neighbor, Bob (strings + production) --
    # not disjoint (both credit strings), so nothing qualifies.
    index = _build()
    alice = next(c for c in index["contributors"] if c["artist_id"] == 100)
    assert alice["interesting_next_step"] is None

    # Bob (Producer) and Carol (Mastered By) are role-disjoint (production
    # vs engineering), but their ONLY shared hop is background-engineering-
    # only on Carol's side (2026-08-31 addendum) -- Carol is excluded from
    # Bob's candidates, and the exclusion is symmetric (Bob is excluded
    # from Carol's too), so BOTH get no interesting_next_step here. See
    # test_interesting_next_step_excludes_a_background_only_pair below for
    # the direct assertion of this exclusion, and
    # test_interesting_next_step_still_picks_a_non_background_disjoint_neighbor
    # for the happy path with a genuinely substantive disjoint neighbor.
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["interesting_next_step"] is None
    carol = next(c for c in index["contributors"] if c["artist_id"] == 300)
    assert carol["interesting_next_step"] is None


def test_interesting_next_step_excludes_a_background_only_pair() -> None:
    """Direct regression guard for the ADR 0060 addendum: a role-disjoint
    neighbor whose ENTIRE shared connection is background-engineering
    credits (Mastered By/Recorded By/Mixed By) must never win the "worth a
    look" slot, even though the role categories are technically disjoint."""
    index = _build()
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    carol = next(c for c in index["contributors"] if c["artist_id"] == 300)
    assert bob["interesting_next_step"] is None
    assert carol["interesting_next_step"] is None


def test_interesting_next_step_still_picks_a_non_background_disjoint_neighbor() -> None:
    """The exclusion is narrow: a role-disjoint neighbor whose shared hop
    carries a REAL substantive role (not background-engineering-only) on
    at least one side still qualifies normally."""
    catalog = {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-1", "title": "First Light", "artist_id": 100, "year": 1995},
            {"id": "master-2", "title": "Second Wave", "artist_id": 200, "year": 2001},
        ],
    }
    challenge = {
        "schema_version": 2,
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [
            {"artist_id": 100, "name": "Alice"},
            {"artist_id": 200, "name": "Bob"},
        ],
        "paths": [
            {
                "id": "path-1",
                "from_album_id": "master-1",
                "to_album_id": "master-2",
                "hops": [{"release_id": 501, "artist_a_id": 100, "artist_b_id": 200}],
            }
        ],
        "releases": [
            _challenge_release(501, [_credit(100, "Guitar"), _credit(200, "Engineer")]),
        ],
    }
    index = build_contributor_index(
        challenge=challenge,
        routes_universe=_routes_universe(),
        routes_rounds={
            "provenance": {"catalog_version": _CATALOG_VERSION},
            "artists": [],
            "rounds": [],
            "releases": [],
        },
        catalog=catalog,
        evidence_release_registry={"release_ids": [], "years": []},
        generated_at="2026-08-03T00:00:00+00:00",
    )
    alice = next(c for c in index["contributors"] if c["artist_id"] == 100)
    # "Engineer" is disjoint from "Guitar" (strings) but is NOT
    # background-engineering-only (only Mastered By/Recorded By/Mixed By
    # are), so this pair is never excluded.
    assert alice["interesting_next_step"] == {
        "artist_id": 200,
        "reason": "credited in a different kind of role than this contributor",
    }


def test_interesting_next_step_never_ranks_by_connection_count_alone() -> None:
    """A real regression guard for the exact bias ADR 0059 measured and
    rejected for Connect's old route scorer: a hub-favoring pick would
    always point toward whichever neighbor has the highest connection_count.
    Here Carol (engineering, connection_count 1) is Bob's ONLY disjoint-role
    candidate even though Alice (connection_count 1 too, but same-category)
    would otherwise tie -- role disjointness gates the candidate set before
    connection_count ever breaks a tie. Uses "Engineer" rather than the
    shared fixture's "Mastered By" for Carol's credit so this pair isn't
    excluded by the 2026-08-31 background-only addendum -- that exclusion
    has its own dedicated tests above."""
    routes_rounds = _routes_rounds()
    routes_rounds["rounds"][0]["hops"][0]["role_b"] = "Engineer"
    index = build_contributor_index(
        challenge=_challenge(),
        routes_universe=_routes_universe(),
        routes_rounds=routes_rounds,
        catalog=_catalog(),
        evidence_release_registry=_evidence_release_registry(),
        generated_at="2026-08-03T00:00:00+00:00",
    )
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["interesting_next_step"]["artist_id"] != 100
    assert bob["interesting_next_step"]["artist_id"] == 300


def test_interesting_next_step_tie_breaks_toward_the_lower_connection_count() -> None:
    """The deliberate anti-hub tie-break: when more than one neighbor has a
    fully disjoint role_categories set, the LOWEST connection_count wins --
    never the highest, which would recreate the exact fame-correlated bias
    ADR 0059 measured and rejected for Connect's old route scorer."""
    catalog = {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {"id": "master-10", "title": "A", "artist_id": 10, "year": 1995},
            {"id": "master-20", "title": "B", "artist_id": 20, "year": 1996},
            {"id": "master-30", "title": "C", "artist_id": 30, "year": 1997},
            {"id": "master-40", "title": "D", "artist_id": 40, "year": 1998},
        ],
    }
    challenge = {
        "schema_version": 2,
        "provenance": {"catalog_version": _CATALOG_VERSION},
        "artists": [
            {"artist_id": 10, "name": "X"},
            {"artist_id": 20, "name": "Y"},
            {"artist_id": 30, "name": "Z"},
            {"artist_id": 40, "name": "W"},
        ],
        "paths": [
            {
                "id": "path-1",
                "from_album_id": "master-10",
                "to_album_id": "master-20",
                "hops": [{"release_id": 501, "artist_a_id": 10, "artist_b_id": 20}],
            },
            {
                "id": "path-2",
                "from_album_id": "master-10",
                "to_album_id": "master-30",
                "hops": [{"release_id": 502, "artist_a_id": 10, "artist_b_id": 30}],
            },
            {
                "id": "path-3",
                "from_album_id": "master-30",
                "to_album_id": "master-40",
                "hops": [{"release_id": 503, "artist_a_id": 30, "artist_b_id": 40}],
            },
        ],
        "releases": [
            _challenge_release(501, [_credit(10, "Guitar"), _credit(20, "Producer")]),
            _challenge_release(502, [_credit(10, "Guitar"), _credit(30, "Engineer")]),
            _challenge_release(503, [_credit(30, "Engineer"), _credit(40, "Vocals")]),
        ],
    }
    index = build_contributor_index(
        challenge=challenge,
        routes_universe=_routes_universe(),
        routes_rounds={
            "provenance": {"catalog_version": _CATALOG_VERSION},
            "artists": [],
            "rounds": [],
            "releases": [],
        },
        catalog=catalog,
        evidence_release_registry={"release_ids": [], "years": []},
        generated_at="2026-08-03T00:00:00+00:00",
    )
    by_id = {c["artist_id"]: c for c in index["contributors"]}
    # Y (production) connects only to X -- connection_count 1.
    assert by_id[20]["connection_count"] == 1
    # Z (engineering) connects to both X and W -- connection_count 2.
    assert by_id[30]["connection_count"] == 2
    # Both Y and Z are role-disjoint from X (strings) -- Y wins on the tie-break.
    assert by_id[10]["interesting_next_step"]["artist_id"] == 20


def test_deterministic_across_repeated_builds() -> None:
    assert _build() == _build()


def test_mismatched_catalog_version_raises() -> None:
    import pytest

    bad_challenge = _challenge()
    bad_challenge["provenance"]["catalog_version"] = "catalog-v1-wrong"
    with pytest.raises(ValueError, match="catalog_version"):
        build_contributor_index(
            challenge=bad_challenge,
            routes_universe=_routes_universe(),
            routes_rounds=_routes_rounds(),
            catalog=_catalog(),
            evidence_release_registry=_evidence_release_registry(),
            generated_at="2026-08-03T00:00:00+00:00",
        )
