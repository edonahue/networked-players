from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_contracts.connection_rounds import (
    round_content_fingerprint as contracts_round_content_fingerprint,
)
from networked_players_graph_core.connection_rounds import (
    ConnectionRoundsValidationError,
    _seeded_shuffle,
    _stable_id,
    artifact_version,
    build_connection_universe_and_rounds,
    generate_connection_round_pool,
    round_content_fingerprint,
    validate_connection_rounds_artifact,
)
from networked_players_graph_core.graph import CreditGraph

SNAPSHOT_DATE = "20260601"


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
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
    role_text: str | None,
    scope: str = "release_credit",
    anv: str | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": name,
        "anv": anv,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _album(
    album_id: str, *, artist_id: int, artist: str, title: str, release_id: int, year: int
) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": None,
        "main_release_id": release_id,
        "title": title,
        "artist_id": artist_id,
        "artist": artist,
        "year": year,
        "cover_image": None,
    }


# Fixture graph (album-centered, distinct from test_rounds_generator.py's
# artist-path fixture): a real performer explicitly credited on BOTH
# displayed albums is what makes a one-hop round, not a shared release with a
# third artist.
#
#   Album A "First Light"  (release 1) -- billed Alice(100); performers
#     Xavier(700, Guitar), Walt(750, Drums, distractor-only)
#   Album C "Third Wave"   (release 2) -- billed Cara(300); performers
#     Xavier(700, Guitar) [shared with A], Uma(760, Bass, distractor-only)
#   Album D "Fourth Chapter" (release 4) -- billed Dan(400); performers
#     Yara(800, Drums) [shared with M], Wendy(150, Bass) [shared with M,
#     deliberately a LOWER artist_id than Yara -- regression fixture for
#     Finding 1/2: the old `min(bridge)` implementation would have picked
#     Wendy as the sole "primary" bridge and wrongly demoted Yara to a
#     distractor], Vic(770, Keys, distractor-only)
#   Album M "Second Set"   (release 3) -- billed Bob(200); performers
#     Yara(800, Drums) [shared with D], Wendy(150, Bass) [shared with D],
#     Zack(900, Organ) [shared with E]
#   Album E "Fifth Session" (release 5) -- billed Eve(500); performers
#     Zack(900, Organ) [shared with M], Tia(780, Sax, distractor-only)
#   Album N "No Shared Performer" (release 6) -- billed Ned(600); performer
#     Fully isolated -- Nea(950, Cello) shares nothing with anyone.
#
# One-hop pairs:  A<->C (Xavier), D<->M (Yara AND Wendy), M<->E (Zack)
# Two-hop pair:   D<->E via the unique middle M (no direct D<->E performer);
#                 bridge_a (D<->M) has TWO valid performers, bridge_c (M<->E)
#                 has one.
# A<->D, A<->E, C<->D, C<->E, *<->N: no shared performer at all.
RELEASES = [
    _release(1, "First Light"),
    _release(2, "Third Wave"),
    _release(3, "Second Set"),
    _release(4, "Fourth Chapter"),
    _release(5, "Fifth Session"),
    _release(6, "No Shared Performer"),
]
CREDITS = [
    _credit(1, artist_id=100, name="Alice", role_text=None, scope="release_artist"),
    _credit(1, artist_id=700, name="Xavier", role_text="Guitar", anv="X. Ray"),
    _credit(1, artist_id=750, name="Walt", role_text="Drums"),
    _credit(2, artist_id=300, name="Cara", role_text=None, scope="release_artist"),
    _credit(2, artist_id=700, name="Xavier", role_text="Guitar"),
    _credit(2, artist_id=760, name="Uma", role_text="Bass"),
    _credit(3, artist_id=200, name="Bob", role_text=None, scope="release_artist"),
    _credit(3, artist_id=800, name="Yara", role_text="Drums"),
    _credit(3, artist_id=150, name="Wendy", role_text="Bass"),
    _credit(3, artist_id=900, name="Zack", role_text="Organ"),
    _credit(4, artist_id=400, name="Dan", role_text=None, scope="release_artist"),
    _credit(4, artist_id=800, name="Yara", role_text="Drums"),
    _credit(4, artist_id=150, name="Wendy", role_text="Bass"),
    _credit(4, artist_id=770, name="Vic", role_text="Keyboards"),
    _credit(5, artist_id=500, name="Eve", role_text=None, scope="release_artist"),
    _credit(5, artist_id=900, name="Zack", role_text="Organ"),
    _credit(5, artist_id=780, name="Tia", role_text="Saxophone"),
    _credit(6, artist_id=600, name="Ned", role_text=None, scope="release_artist"),
    _credit(6, artist_id=950, name="Nea", role_text="Cello"),
    # A non-performer credit (Producer) must never surface as an answer or a
    # distractor -- is_performer_role excludes it before it reaches the pool.
    _credit(1, artist_id=999, name="Prod Perry", role_text="Producer"),
]

ALBUMS = [
    _album("album-a", artist_id=100, artist="Alice", title="First Light", release_id=1, year=1995),
    _album("album-c", artist_id=300, artist="Cara", title="Third Wave", release_id=2, year=1996),
    _album("album-m", artist_id=200, artist="Bob", title="Second Set", release_id=3, year=1997),
    _album("album-d", artist_id=400, artist="Dan", title="Fourth Chapter", release_id=4, year=1998),
    _album("album-e", artist_id=500, artist="Eve", title="Fifth Session", release_id=5, year=1999),
    _album(
        "album-n", artist_id=600, artist="Ned", title="No Shared Performer", release_id=6, year=2000
    ),
]


@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    from conftest import write_synthetic_dataset

    return write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}", release_rows=RELEASES, credit_rows=CREDITS
    )


def test_generate_finds_one_and_two_hop_rounds(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        # Disable diversity caps -- this 6-album fixture is far below the
        # scale those caps are meant for (matches test_rounds_generator.py's
        # own precedent), and this test wants every real candidate selected.
        rounds, diagnostics, _idx = generate_connection_round_pool(
            graph,
            ALBUMS,
            one_hop_target=10,
            two_hop_target=10,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )
    assert diagnostics["one_hop_candidates_found"] == 3  # A-C, D-M, M-E
    assert diagnostics["two_hop_candidates_found"] == 1  # D-E via M
    one_hop_pairs = {
        frozenset((r["endpoints"][0]["id"], r["endpoints"][1]["id"]))
        for r in rounds
        if r["kind"] == "one_hop"
    }
    assert one_hop_pairs == {
        frozenset({"album-a", "album-c"}),
        frozenset({"album-d", "album-m"}),
        frozenset({"album-m", "album-e"}),
    }
    two_hop = [r for r in rounds if r["kind"] == "two_hop"]
    assert len(two_hop) == 1
    assert {two_hop[0]["endpoints"][0]["id"], two_hop[0]["endpoints"][1]["id"]} == {
        "album-d",
        "album-e",
    }
    assert two_hop[0]["middle"]["album"]["id"] == "album-m"


def test_one_hop_answer_is_the_real_shared_performer(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _, _idx = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    ac_round = next(
        r
        for r in rounds
        if r["kind"] == "one_hop"
        and {r["endpoints"][0]["id"], r["endpoints"][1]["id"]} == {"album-a", "album-c"}
    )
    assert [a["id"] for a in ac_round["answer_set"]] == [700]
    assert ac_round["answer_set"][0]["name"] == "Xavier"
    assert ac_round["answer_set"][0]["role_category"] == "guitar"


def test_non_performer_credit_never_surfaces(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _, _idx = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    for round_json in rounds:
        ids = {a["id"] for a in round_json["answer_set"]} | {
            d["id"] for d in round_json["distractors"]
        }
        for bridge_set in round_json.get("bridge_answer_sets") or []:
            ids |= {a["id"] for a in bridge_set}
        assert 999 not in ids


def test_distractors_never_satisfy_the_connection(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _, _idx = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    for round_json in rounds:
        answer_ids = {a["id"] for a in round_json["answer_set"]}
        for bridge_set in round_json.get("bridge_answer_sets") or []:
            answer_ids |= {a["id"] for a in bridge_set}
        distractor_ids = {d["id"] for d in round_json["distractors"]}
        assert not (answer_ids & distractor_ids)


def test_family_exclusion_drops_the_pair(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, diagnostics, _idx = generate_connection_round_pool(
            graph,
            ALBUMS,
            one_hop_target=10,
            two_hop_target=10,
            is_family_excluded=lambda a, b: {a, b} == {100, 300},
        )
    assert diagnostics["one_hop_candidates_found"] == 2
    pairs = {frozenset((r["endpoints"][0]["id"], r["endpoints"][1]["id"])) for r in rounds}
    assert frozenset({"album-a", "album-c"}) not in pairs


def test_isolated_album_never_becomes_a_round_endpoint(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _, _idx = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    referenced = set()
    for r in rounds:
        referenced.add(r["endpoints"][0]["id"])
        referenced.add(r["endpoints"][1]["id"])
    assert "album-n" not in referenced


def test_build_universe_only_includes_round_referenced_albums(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    # The universe is built exactly from what the rounds reference (endpoint,
    # middle, or a decoy middle choice) -- never padded with every input
    # album regardless of use. album-n has no shared performer with anything
    # but can still legitimately appear as a two-hop decoy choice (any other
    # real album is a valid "not the hidden middle" option), so this checks
    # exact equality against the real reference set, not a hand-picked subset.
    referenced_ids: set[str] = set()
    for round_json in rounds_json:
        referenced_ids.add(round_json["endpoints"][0]["id"])
        referenced_ids.add(round_json["endpoints"][1]["id"])
        middle = round_json.get("middle")
        if middle:
            referenced_ids.add(middle["album"]["id"])
            referenced_ids.update(c["id"] for c in middle["choices"])
    album_ids = {a["id"] for a in universe["albums"]}
    assert album_ids == referenced_ids
    assert {"album-a", "album-c", "album-d", "album-m", "album-e"} <= album_ids
    validate_connection_rounds_artifact(universe, rounds)  # does not raise


def test_validate_rejects_answer_without_evidence(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    rounds["rounds"][0]["evidence"] = []
    with pytest.raises(ConnectionRoundsValidationError, match="lacks evidence"):
        validate_connection_rounds_artifact(universe, rounds)


def test_validate_rejects_wrong_pool_label(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    rounds["rounds"][0]["pool"] = "synthetic-universe"
    with pytest.raises(ConnectionRoundsValidationError, match="real-records"):
        validate_connection_rounds_artifact(universe, rounds)


def test_validate_rejects_forbidden_substring(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    universe["provenance"]["note"] += " see /home/erich/notes"
    with pytest.raises(ConnectionRoundsValidationError, match="forbidden substring"):
        validate_connection_rounds_artifact(universe, rounds)


def test_no_eligible_pairs_returns_empty_pool(tmp_path: Path) -> None:
    from conftest import write_synthetic_dataset

    root = write_synthetic_dataset(
        tmp_path / f"snapshot={SNAPSHOT_DATE}",
        release_rows=[_release(1, "Solo Album")],
        credit_rows=[
            _credit(1, artist_id=100, name="Alice", role_text=None, scope="release_artist")
        ],
    )
    solo_album = [
        _album(
            "album-a", artist_id=100, artist="Alice", title="Solo Album", release_id=1, year=1995
        )
    ]
    with CreditGraph.open(root, build_edges=False) as graph:
        rounds, diagnostics, _idx = generate_connection_round_pool(
            graph, solo_album, one_hop_target=10, two_hop_target=10
        )
    assert rounds == []
    assert diagnostics["one_hop_candidates_found"] == 0


# --- Corrective slice 4.5 regression tests (Findings 1, 2, 3, 5, 6, 7) ------


def _two_hop_round(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    return next(r for r in rounds if r["kind"] == "two_hop")


def test_two_hop_bridge_includes_every_valid_performer_not_just_lowest_id(
    dataset_root: Path,
) -> None:
    """Finding 1/2 regression: bridge_a (D<->M) has TWO real shared
    performers, Wendy(150) and Yara(800). The old `min(bridge)`
    implementation would have published only Wendy (lower id) as the answer
    and left Yara eligible as a "proven wrong" distractor -- a real bug,
    since Yara genuinely does satisfy the connection."""
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _, _idx = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    round_json = _two_hop_round(rounds)
    bridge_a_ids = {a["id"] for a in round_json["bridge_answer_sets"][0]}
    bridge_c_ids = {a["id"] for a in round_json["bridge_answer_sets"][1]}
    assert bridge_a_ids == {150, 800}
    assert bridge_c_ids == {900}
    distractor_ids = {d["id"] for d in round_json["distractors"]}
    assert not (bridge_a_ids | bridge_c_ids) & distractor_ids
    # Every bridge answer needs its own evidence, not just the primary's.
    evidence_ids = {row["contributor_id"] for row in round_json["evidence"]}
    assert bridge_a_ids <= evidence_ids
    assert bridge_c_ids <= evidence_ids


def test_contributor_ref_uses_canonical_name_not_anv(dataset_root: Path) -> None:
    """Finding 1 regression: Xavier's release-1 credit carries an ANV
    ("X. Ray"). `ContributorRef.name` must stay the canonical PAN name in
    every round that names him, while `EvidenceRow.credited_as` is free to
    show the as-credited ANV spelling for that specific release."""
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _, _idx = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    ac_round = next(
        r
        for r in rounds
        if r["kind"] == "one_hop"
        and {r["endpoints"][0]["id"], r["endpoints"][1]["id"]} == {"album-a", "album-c"}
    )
    assert ac_round["answer_set"][0]["name"] == "Xavier"
    evidence_on_album_a = next(
        row for row in ac_round["evidence"] if row["release_ref"] == "album-a"
    )
    assert evidence_on_album_a["credited_as"] == "X. Ray"


def test_multi_answer_clue_wording_is_honest(dataset_root: Path) -> None:
    """Finding 5 regression: the D<->M one-hop round has two valid answers
    (Wendy, Yara). The role/initials clues must not read as if only one
    connecting person/role exists."""
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds, _, _idx = generate_connection_round_pool(
            graph,
            ALBUMS,
            one_hop_target=10,
            two_hop_target=10,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )
    dm_round = next(
        r
        for r in rounds
        if r["kind"] == "one_hop"
        and {r["endpoints"][0]["id"], r["endpoints"][1]["id"]} == {"album-d", "album-m"}
    )
    assert len(dm_round["answer_set"]) == 2
    role_clue = next(c for c in dm_round["clues"] if c["kind"] == "role")
    initials_clue = next(c for c in dm_round["clues"] if c["kind"] == "initials")
    assert "among other valid answers" in role_clue["text"]
    assert "one of several valid answers" in initials_clue["text"]

    ac_round = next(
        r
        for r in rounds
        if r["kind"] == "one_hop"
        and {r["endpoints"][0]["id"], r["endpoints"][1]["id"]} == {"album-a", "album-c"}
    )
    assert len(ac_round["answer_set"]) == 1
    single_role_clue = next(c for c in ac_round["clues"] if c["kind"] == "role")
    assert "among other valid answers" not in single_role_clue["text"]


def test_stable_round_id_survives_pool_regeneration(dataset_root: Path) -> None:
    """Finding 6 regression: a round's id must depend only on its own
    semantic content (endpoints + answers), never on selection order or
    which other rounds happen to be in the pool. Regenerating with a smaller
    target (a different selected subset/order) must not change the id of a
    round that is selected both times."""
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        full_rounds, _, _idx = generate_connection_round_pool(
            graph,
            ALBUMS,
            one_hop_target=10,
            two_hop_target=10,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )
        small_rounds, _, _idx2 = generate_connection_round_pool(
            graph,
            ALBUMS,
            one_hop_target=1,
            two_hop_target=1,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )
    full_by_pair = {
        frozenset((r["endpoints"][0]["id"], r["endpoints"][1]["id"])): r["id"] for r in full_rounds
    }
    assert small_rounds, "expected at least one round in the smaller regeneration"
    for round_json in small_rounds:
        pair = frozenset((round_json["endpoints"][0]["id"], round_json["endpoints"][1]["id"]))
        assert full_by_pair[pair] == round_json["id"]


def test_stable_id_changes_only_when_semantics_change() -> None:
    assert _stable_id("1h", "album-a", "album-c", "700") == _stable_id(
        "1h", "album-a", "album-c", "700"
    )
    assert _stable_id("1h", "album-a", "album-c", "700") != _stable_id(
        "1h", "album-a", "album-c", "701"
    )
    assert _stable_id("1h", "album-a", "album-c", "700") != _stable_id(
        "1h", "album-a", "album-d", "700"
    )


def test_seeded_shuffle_is_deterministic_and_seed_dependent() -> None:
    items = [{"id": str(i)} for i in range(8)]
    a = [dict(item) for item in items]
    b = [dict(item) for item in items]
    _seeded_shuffle(a, "conn-aaaaaaaaaa")
    _seeded_shuffle(b, "conn-aaaaaaaaaa")
    assert a == b  # same seed -> same permutation, every time

    c = [dict(item) for item in items]
    _seeded_shuffle(c, "conn-bbbbbbbbbb")
    assert a != c  # different seed -> (overwhelmingly likely) different permutation


def test_middle_choice_order_is_a_deterministic_function_of_round_id(dataset_root: Path) -> None:
    """Finding 3 regression: the previous implementation always placed the
    real middle at index 0 (`choices = [middle_ref] + [...]`), making the
    hidden-middle step trivially guessable without evidence. Regenerating
    the whole pool twice, independently, must reproduce the exact same
    choices order both times (deterministic, seeded by the round's own
    stable content -- never wall-clock randomness or dict/insertion order).
    (Non-first-position across the whole pool is checked at real scale in
    the corrective-slice-4.5 PR comment's answer-position distribution -- a
    single-round fixture can't make a distributional claim without
    flakiness.)"""
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        first, _, _idx1 = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
        second, _, _idx2 = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    first_round = _two_hop_round(first)
    second_round = _two_hop_round(second)
    assert len(first_round["middle"]["choices"]) > 1, "fixture must offer a real choice"
    assert first_round["middle"]["choices"] == second_round["middle"]["choices"]


def test_universe_credits_are_a_complete_index_not_evidence_only(dataset_root: Path) -> None:
    """Finding 7 regression: the universe's credits must include EVERY
    eligible performer on a used album, not just the ones cited as evidence
    for an already-selected round's answer. Walt(750) and Vic(770) are real
    performers on album-a/album-d but never a round's answer (they share no
    performer with anything) -- they must still appear in the universe so an
    independent consumer can re-derive "no shared performer" for themselves."""
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, _rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    contributor_ids = {c["id"] for c in universe["contributors"]}
    assert 750 in contributor_ids  # Walt: real performer on album-a, never an answer
    assert 770 in contributor_ids  # Vic: real performer on album-d, never an answer
    credit_pairs = {(c["release_id"], c["contributor_id"]) for c in universe["credits"]}
    assert ("album-a", 750) in credit_pairs
    assert ("album-d", 770) in credit_pairs


def test_validator_requires_catalog_and_pool_version(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version=None,
    )
    with pytest.raises(ConnectionRoundsValidationError, match="catalog_version"):
        validate_connection_rounds_artifact(universe, rounds)


def test_validator_rejects_unstable_round_id(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    rounds["rounds"][0]["id"] = "conn-000001"
    with pytest.raises(ConnectionRoundsValidationError, match="not a stable content-derived id"):
        validate_connection_rounds_artifact(universe, rounds)


# --- Corrective slice 4.6: pool_version (membership) vs artifact_version ----
# (complete content) separation, and shared stable-id/fingerprint recomputation
# between the generation-time and dependency-free validators.


def test_content_fingerprint_ignores_json_whitespace_and_key_order() -> None:
    round_a = {"id": "conn-x", "clues": [{"kind": "years", "text": "1990"}], "answer_set": []}
    # A dict built with different literal key/insertion order is the same
    # value -- canonical serialization must hash it identically.
    round_b = {"answer_set": [], "id": "conn-x", "clues": [{"text": "1990", "kind": "years"}]}
    assert round_content_fingerprint(round_a) == round_content_fingerprint(round_b)


def test_content_fingerprint_changes_on_a_distractor_edit() -> None:
    base = {"id": "conn-x", "distractors": [{"id": 1, "name": "Alice"}]}
    edited = {"id": "conn-x", "distractors": [{"id": 1, "name": "Alicia"}]}
    assert round_content_fingerprint(base) != round_content_fingerprint(edited)


def test_content_fingerprint_changes_on_a_clue_edit() -> None:
    base = {"id": "conn-x", "clues": [{"kind": "role", "text": "Guitar work."}]}
    edited = {"id": "conn-x", "clues": [{"kind": "role", "text": "Bass work."}]}
    assert round_content_fingerprint(base) != round_content_fingerprint(edited)


def test_content_fingerprint_changes_on_an_evidence_edit() -> None:
    base = {"id": "conn-x", "evidence": [{"role_text": "Guitar"}]}
    edited = {"id": "conn-x", "evidence": [{"role_text": "Guitar, Vocals"}]}
    assert round_content_fingerprint(base) != round_content_fingerprint(edited)


def test_content_fingerprint_changes_on_middle_choice_order() -> None:
    base = {"id": "conn-x", "middle": {"choices": [{"id": "a"}, {"id": "b"}]}}
    reordered = {"id": "conn-x", "middle": {"choices": [{"id": "b"}, {"id": "a"}]}}
    assert round_content_fingerprint(base) != round_content_fingerprint(reordered)


def test_content_fingerprint_shared_with_dependency_free_mirror() -> None:
    """Not a structural mirror -- both call the SAME
    networked_players_contracts.canonical.content_hash primitive, so this
    test would fail if either side stopped importing the shared module."""
    sample = {"id": "conn-x", "clues": [{"kind": "role", "text": "Bass work."}]}
    assert round_content_fingerprint(sample) == contracts_round_content_fingerprint(sample)


def test_pool_version_is_membership_only_artifact_version_is_complete_content(
    dataset_root: Path,
) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph,
            ALBUMS,
            one_hop_target=10,
            two_hop_target=10,
            max_endpoint_share=1.0,
            max_bridge_share=1.0,
        )
    universe, _rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    original_pool_version = universe["provenance"]["pool_version"]
    original_artifact_version = universe["provenance"]["artifact_version"]

    # Edit a distractor's display name on one round -- membership (which
    # round ids are in the pool) is unchanged, so pool_version must be
    # unchanged; the published content changed, so artifact_version must not
    # match a fresh recomputation from the edited rounds.
    edited_rounds = [dict(r) for r in rounds_json]
    edited_rounds[0] = dict(edited_rounds[0])
    edited_rounds[0]["distractors"] = [
        {**d, "name": d["name"] + " Jr."} for d in edited_rounds[0]["distractors"]
    ]
    edited_universe, edited_artifact = build_connection_universe_and_rounds(
        ALBUMS,
        edited_rounds,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    assert edited_universe["provenance"]["pool_version"] == original_pool_version
    assert edited_universe["provenance"]["artifact_version"] != original_artifact_version
    assert edited_artifact["rounds"][0]["id"] == rounds_json[0]["id"]  # identity unchanged


def test_validator_recomputes_and_rejects_stale_artifact_version(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    rounds["rounds"][0]["distractors"][0]["name"] = "Someone Else"
    with pytest.raises(ConnectionRoundsValidationError, match="artifact_version"):
        validate_connection_rounds_artifact(universe, rounds)


def test_validator_rejects_round_id_not_matching_its_own_semantic_fields(
    dataset_root: Path,
) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    # A syntactically valid id that just doesn't belong to this round's own
    # endpoints/answers -- this is the recomputation check, distinct from
    # the format-only regex check.
    other_round = next(r for r in rounds["rounds"] if r["id"] != rounds["rounds"][0]["id"])
    rounds["rounds"][0]["id"] = other_round["id"]
    with pytest.raises(
        ConnectionRoundsValidationError, match="does not match its own recomputed content"
    ):
        validate_connection_rounds_artifact(universe, rounds)


def test_artifact_version_helper_agrees_with_generation(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, _rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    assert universe["provenance"]["artifact_version"] == artifact_version(
        rounds_json, SNAPSHOT_DATE
    )


# --- Corrective slice 5.1: artifact_version reflects PUBLISHED ORDER --------


def test_artifact_version_changes_when_two_rounds_are_swapped() -> None:
    a = {"id": "conn-a", "clues": [{"kind": "years", "text": "1990"}]}
    b = {"id": "conn-b", "clues": [{"kind": "years", "text": "1991"}]}
    forward = artifact_version([a, b], SNAPSHOT_DATE)
    swapped = artifact_version([b, a], SNAPSHOT_DATE)
    assert forward != swapped


def test_artifact_version_unchanged_by_json_formatting_only() -> None:
    # Same value, different dict literal insertion order -- canonical
    # serialization must still agree (see canonical_json).
    a = [{"id": "conn-a", "clues": [{"kind": "years", "text": "1990"}]}]
    b = [{"clues": [{"text": "1990", "kind": "years"}], "id": "conn-a"}]
    assert artifact_version(a, SNAPSHOT_DATE) == artifact_version(b, SNAPSHOT_DATE)


def test_artifact_version_unchanged_when_ordered_content_is_unchanged() -> None:
    rounds = [
        {"id": "conn-a", "clues": [{"kind": "years", "text": "1990"}]},
        {"id": "conn-b", "clues": [{"kind": "years", "text": "1991"}]},
    ]
    assert artifact_version(rounds, SNAPSHOT_DATE) == artifact_version(rounds, SNAPSHOT_DATE)


# --- Slice 7A: frozen game content is art-free (ADR 0045) -------------------


def test_generated_universe_and_rounds_are_art_free(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    for album in universe["albums"]:
        assert album["art"] is None
    for round_json in rounds["rounds"]:
        for endpoint in round_json["endpoints"]:
            assert endpoint["art"] is None
        middle = round_json.get("middle")
        if middle:
            assert middle["album"]["art"] is None
            for choice in middle["choices"]:
                assert choice["art"] is None
    validate_connection_rounds_artifact(universe, rounds)  # does not raise


def test_validator_rejects_embedded_hotlink_art(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    rounds["rounds"][0]["endpoints"][0]["art"] = {
        "kind": "hotlink",
        "uri150": "https://i.discogs.com/x/150.jpg",
        "uri": "https://i.discogs.com/x/full.jpg",
    }
    with pytest.raises(ConnectionRoundsValidationError, match="embeds mutable cover art"):
        validate_connection_rounds_artifact(universe, rounds)


def test_validator_rejects_two_hop_round_whose_endpoints_share_a_direct_performer(
    dataset_root: Path,
) -> None:
    """Universe-derived check (no graph needed, Finding 7): if a two-hop
    round's own endpoints turn out to share a direct eligible performer per
    the published universe, the round's whole premise is violated -- it
    should have been generated as one-hop."""
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        rounds_json, _, performer_index = generate_connection_round_pool(
            graph, ALBUMS, one_hop_target=10, two_hop_target=10
        )
    universe, rounds = build_connection_universe_and_rounds(
        ALBUMS,
        rounds_json,
        performer_index,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test",
        catalog_version="test-catalog-v1",
    )
    two_hop = next(r for r in rounds["rounds"] if r["kind"] == "two_hop")
    a_id, c_id = two_hop["endpoints"][0]["id"], two_hop["endpoints"][1]["id"]
    # Manufacture a shared performer between the two endpoints directly.
    universe["credits"].append(
        {
            "release_id": a_id,
            "contributor_id": 999999,
            "role_text": "Guitar",
            "role_category": "guitar",
            "credit_scope": "release_credit",
        }
    )
    universe["credits"].append(
        {
            "release_id": c_id,
            "contributor_id": 999999,
            "role_text": "Guitar",
            "role_category": "guitar",
            "credit_scope": "release_credit",
        }
    )
    universe["contributors"].append({"id": 999999, "name": "Ringer", "role_category": "guitar"})
    with pytest.raises(ConnectionRoundsValidationError, match="premise violated"):
        validate_connection_rounds_artifact(universe, rounds)
