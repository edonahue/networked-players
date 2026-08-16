from __future__ import annotations

from typing import Any

from networked_players_graph_core.contributor_index import build_contributor_index
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

    # Bob (strings + production) has two neighbors: Alice (strings, shares a
    # category) and Carol (engineering only, fully disjoint) -- Carol wins.
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["interesting_next_step"] == {
        "artist_id": 300,
        "reason": "credited in a different kind of role than this contributor",
    }

    # Carol (engineering only) has one neighbor, Bob (strings + production)
    # -- fully disjoint from Carol's own roles, so Bob is her pick too
    # (symmetric, but not required to be -- each side evaluates its own
    # role_categories against the other's).
    carol = next(c for c in index["contributors"] if c["artist_id"] == 300)
    assert carol["interesting_next_step"] == {
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
    connection_count ever breaks a tie."""
    index = _build()
    bob = next(c for c in index["contributors"] if c["artist_id"] == 200)
    assert bob["interesting_next_step"]["artist_id"] != 100


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
