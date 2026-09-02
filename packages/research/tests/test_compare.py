"""Phase 7 PR D, Slice 1: `compare_albums` over a small synthetic corpus
built the same way every other package here builds one (never real data).

Fixture shape: R1/R2 share a real contributor (Carol) for the direct-route
case; R1/R3 share no contributor but ARE bridged through R4 (Carol performs
with Dan there), for the indirect-route case; R6 is fully isolated from R1
for the no-path case; R5 is a various-artists release with no single
`release_artist`, for the scope-tier "not_applicable" case.

Every artist meant to participate in a traversal edge gets the same two-row
shape `packages/graph-core/tests/conftest.py`'s `_performed` helper uses
(`release_artist` + `track_artist` on the same `track_index`) -- co-billed,
co-performing artists on an album-shaped release, matching `credit_edges_sql`'s
real `co_performers` rule. A `release_credit`-scope contributor whose role
text documents a real performance (Carol, Violin; Deb, Drums) still forms a
`release_scope` edge on its own. Bob (Engineer) is the deliberate negative
case: a single `release_credit`-scope row whose role documents no
performance, so ADR 0068's gate keeps him credited but never graph-
traversable -- counted by anything that reads raw credits, never a neighbor
in anything that reads `credit_edges`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.graph import CreditGraph, EvidencePath, FrontierTooLargeError, Hop
from networked_players_research.compare import (
    CompareAlbumsRequest,
    CompareArtistsRequest,
    CompareError,
    _route_between,
    _sorted_role_texts,
    compare_albums,
    run_comparison_and_persist,
)
from networked_players_research.report import ResearchReportError, _scan_for_forbidden_phrases

from .conftest import _credit, _release, write_synthetic_dataset

SEED_A = 100
BOB = 200
CAROL = 300
SEED_B = 400
SEED_C = 500
DAN = 600
EVE = 700
FRANK = 800
SEED_F = 900
GINA = 1000
DEB = 1100


def _performed(release_id: int, *, artist_id: int, name: str) -> list[dict[str, Any]]:
    return [
        _credit(release_id, artist_id=artist_id, name=name, scope="release_artist"),
        _credit(
            release_id,
            artist_id=artist_id,
            name=name,
            scope="track_artist",
            role_text=None,
            track_index=0,
        ),
    ]


def _build_corpus(tmp_path: Path) -> Path:
    """Plain function, not the `corpus` fixture itself, so `test_cli_compare.py`
    can build the same corpus directly -- calling a `@pytest.fixture`-wrapped
    function outside pytest's own injection needs `.__wrapped__`, which isn't
    a typed attribute pytest exposes."""
    releases = [
        _release(1, "Album Alpha", released="1990"),
        _release(2, "Album Beta", released="1991"),
        _release(3, "Album Gamma", released="1992"),
        _release(4, "Bridge Session", released="1992"),
        _release(5, "Field Recordings Various Artists", released="1993"),
        _release(6, "Isolated Album", released="1994"),
    ]

    credits: list[dict[str, Any]] = []
    # R1: Seed A (billed, Vocals) + Carol (co-performer, Strings) + Deb
    # (release-scope, Drums -- a second real performer-qualifying edge,
    # distinct role category from Carol's) + Bob (release-scope credit
    # only, Engineer -- ADR 0068: documents no performance, so credited but
    # never graph-traversable; kept only for role_category_counts-style
    # tests that inspect an artist's own raw credits, not graph edges).
    credits += [
        _credit(1, artist_id=SEED_A, name="Seed A", scope="release_artist", role_text="Vocals"),
        _credit(
            1,
            artist_id=SEED_A,
            name="Seed A",
            scope="track_artist",
            role_text="Vocals",
            track_index=0,
        ),
        # release_credit, not release_artist -- Seed A stays the sole
        # release_artist-scope credit (needed for the scope-tier primary-
        # artist resolution below); Carol is still a real credited
        # contributor on R1 either way.
        _credit(1, artist_id=CAROL, name="Carol", scope="release_credit", role_text="Violin"),
        _credit(1, artist_id=DEB, name="Deb", scope="release_credit", role_text="Drums"),
        _credit(1, artist_id=BOB, name="Bob", scope="release_credit", role_text="Engineer"),
    ]
    # R2: Seed B (sole release_artist, needed for scope-tier resolution) +
    # Carol again (release_credit, same as R1) -- the direct shared
    # contributor.
    credits += _performed(2, artist_id=SEED_B, name="Seed B")
    credits.append(
        _credit(2, artist_id=CAROL, name="Carol", scope="release_credit", role_text="Violin")
    )
    # R3: Seed C (billed) + Dan -- no overlap with R1 at all.
    credits += _performed(3, artist_id=SEED_C, name="Seed C")
    credits += _performed(3, artist_id=DAN, name="Dan")
    # R4: Carol + Dan co-perform -- the real bridge edge between R1 and R3.
    credits += _performed(4, artist_id=CAROL, name="Carol")
    credits += _performed(4, artist_id=DAN, name="Dan")
    # R5: two release_artist-scope credits -- no single primary artist.
    credits += [
        _credit(5, artist_id=EVE, name="Eve", scope="release_artist", role_text=None),
        _credit(5, artist_id=FRANK, name="Frank", scope="release_artist", role_text=None),
    ]
    # R6: Seed F + Gina, fully isolated from everyone else.
    credits += _performed(6, artist_id=SEED_F, name="Seed F")
    credits += _performed(6, artist_id=GINA, name="Gina")

    root = tmp_path / "snapshot=20260601"
    return write_synthetic_dataset(root, release_rows=releases, credit_rows=credits)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return _build_corpus(tmp_path)


def test_sorted_role_texts_handles_a_mix_of_none_and_real_role_text() -> None:
    # Found running research-compare against the real, already-built
    # Jamiroquai topic corpus (not caught by the synthetic fixture below):
    # a release_artist-scope credit with no role_text alongside a
    # track_artist-scope credit WITH one, for the same artist on the same
    # release, is real Discogs data, not an edge case -- plain `sorted()`
    # on a set containing both raises TypeError immediately.
    rows: list[dict[str, Any]] = [
        {"role_text": None},
        {"role_text": "Vocals"},
        {"role_text": None},
    ]
    assert _sorted_role_texts(rows) == ["Vocals", None]


def test_shared_and_unique_contributors_both_directions(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 1, 2))

    shared_ids = {p["artist_id"] for p in result["shared_vs_unique"]["recurring_personnel"]}
    assert shared_ids == {CAROL}
    assert set(result["shared_vs_unique"]["unique_to_album_a"]) == {SEED_A, BOB, DEB}
    assert set(result["shared_vs_unique"]["unique_to_album_b"]) == {SEED_B}


def test_album_evidence_retains_a_non_linked_credit_row(tmp_path: Path) -> None:
    # A real Codex-review-caught bug: credit_rows_for_releases (the plain,
    # roster-only method) drops non-linked credits (artist_id IS NULL)
    # entirely -- AGENTS.md requires retaining them as evidence, never
    # silently dropping them, even though they can never become playable
    # graph identities. compare_albums must use the `_with_evidence`
    # sibling for its own credit_rows output.
    releases = [_release(201, "Album With A Choir"), _release(202, "Plain Album")]
    credits = [
        *_performed(201, artist_id=SEED_A, name="Seed A"),
        _credit(
            201,
            artist_id=None,
            name="Session Choir",
            scope="release_credit",
            is_linked=False,
            playable_identity=False,
        ),
        *_performed(202, artist_id=SEED_B, name="Seed B"),
    ]
    corpus = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=releases, credit_rows=credits
    )
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 201, 202))

    names_in_evidence = {row["name"] for row in result["album_a"]["credit_rows"]}
    assert names_in_evidence == {"Seed A", "Session Choir"}
    # The non-linked row must never leak into graph-roster computation --
    # unique_to_album_a should still be just the real, linked contributor.
    assert result["shared_vs_unique"]["unique_to_album_a"] == [SEED_A]


def test_role_category_composition_matches_classify_role(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 1, 2))

    # R1: Seed A "Vocals" (release_artist + track_artist -> same category,
    # deduped to one), Carol "Violin", Bob "Engineer".
    counts = result["album_a"]["role_category_counts"]
    assert counts.get("vocals") == 1
    assert counts.get("strings") == 1
    assert counts.get("engineering") == 1


def test_direct_route_found_when_albums_share_a_contributor(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 1, 2))

    assert result["direct_route"] == {"connected": True, "shared_artist_ids": [CAROL]}
    assert result["indirect_route"] is None


def test_indirect_route_found_via_a_real_bridge_artist(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 1, 3, max_hops=4))

    assert result["direct_route"] == {"connected": False}
    indirect = result["indirect_route"]
    assert indirect is not None
    assert indirect["case"] == "found"
    # Candidates are tried lowest-degree-first on each side (to avoid a hub
    # artist dominating every result), not globally-shortest-path-first --
    # so the real bridge (Carol/R1 <-> Dan/R3 via their R4 co-performance,
    # one hop) may or may not be the specific pair found here. What must
    # hold regardless: the endpoints belong to the right rosters, and the
    # hop chain is real, evidenced, and actually connects them.
    assert indirect["from_artist_id"] in {SEED_A, CAROL, BOB, DEB}
    assert indirect["to_artist_id"] in {SEED_C, DAN}
    assert 1 <= len(indirect["hops"]) <= 4
    chain = [indirect["from_artist_id"]] + [hop["artist_b_id"] for hop in indirect["hops"]]
    assert chain[0] == indirect["from_artist_id"]
    assert chain[-1] == indirect["to_artist_id"]
    for hop, expected_a in zip(indirect["hops"], chain[:-1], strict=True):
        assert hop["artist_a_id"] == expected_a


def test_no_path_within_bound_when_no_route_exists(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 1, 6, max_hops=4))

    assert result["direct_route"] == {"connected": False}
    assert result["indirect_route"]["case"] == "no_path_within_bound"


def test_search_bounded_is_never_confused_with_a_confirmed_no_path(corpus: Path) -> None:
    # A real route exists (R1 -> R3 via Carol/Dan), but a candidate-pair
    # budget of 0 must report "search_bounded", NEVER "no_path_within_bound"
    # -- the whole point of the distinction the plan calls for.
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(
            graph, CompareAlbumsRequest(corpus, 1, 3, max_route_candidate_pairs=0)
        )

    assert result["indirect_route"]["case"] == "search_bounded"
    assert result["indirect_route"]["case"] != "no_path_within_bound"


class _FakeGraph:
    """A minimal `CreditGraph` double exposing only what `_route_between`
    calls (`degrees`, `find_path`) -- lets the pair-budget/frontier-capped
    logic be tested deterministically, without needing a real fixture
    engineered to make a specific candidate pair fail or succeed."""

    def __init__(
        self,
        degrees: dict[int, int],
        *,
        paths: dict[tuple[int, int], EvidencePath | None] | None = None,
        raises_for: set[tuple[int, int]] | None = None,
    ) -> None:
        self._degrees = degrees
        self._paths = paths or {}
        self._raises_for = raises_for or set()

    def degrees(self, artist_ids: list[int]) -> dict[int, int]:
        return {a: self._degrees.get(a, 0) for a in artist_ids}

    def find_path(self, from_id: int, to_id: int, *, max_hops: int) -> EvidencePath | None:
        if (from_id, to_id) in self._raises_for:
            raise FrontierTooLargeError(frozenset({from_id}))
        return self._paths.get((from_id, to_id))


def test_route_between_reports_search_bounded_when_the_pair_budget_runs_out_mid_loop() -> None:
    # Candidates ordered by ascending degree: A -> [1, 2], B -> [10, 20].
    # A real path exists for (2, 20), but a budget of 2 only reaches (1, 10)
    # and (1, 20) before stopping -- must report "search_bounded", not
    # "no_path_within_bound", even though every TRIED pair came up empty.
    graph = _FakeGraph(
        degrees={1: 0, 2: 1, 10: 0, 20: 1},
        paths={(2, 20): EvidencePath(from_artist_id=2, to_artist_id=20, hops=(Hop(1, 2, 20),))},
    )
    result = _route_between(graph, [1, 2], [10, 20], max_hops=4, max_route_candidate_pairs=2)
    assert result == {"case": "search_bounded", "pairs_tried": 2}


def test_route_between_finds_a_later_pair_within_a_sufficient_budget() -> None:
    graph = _FakeGraph(
        degrees={1: 0, 2: 1, 10: 0, 20: 1},
        paths={(2, 20): EvidencePath(from_artist_id=2, to_artist_id=20, hops=(Hop(1, 2, 20),))},
    )
    result = _route_between(graph, [1, 2], [10, 20], max_hops=4, max_route_candidate_pairs=4)
    assert result["case"] == "found"
    assert result["from_artist_id"] == 2
    assert result["to_artist_id"] == 20


def test_route_between_reports_no_path_within_bound_only_when_every_pair_was_genuinely_tried() -> (
    None
):
    graph = _FakeGraph(degrees={1: 0, 10: 0})
    result = _route_between(graph, [1], [10], max_hops=4, max_route_candidate_pairs=100)
    assert result == {"case": "no_path_within_bound", "pairs_tried": 1}


def test_route_between_reports_search_bounded_when_a_pair_was_frontier_capped() -> None:
    # Every pair is nominally "tried" within budget, but one attempt raised
    # FrontierTooLargeError -- the search is inconclusive for that pair, so
    # the overall result must be "search_bounded," never a confirmed
    # "no_path_within_bound," even though no exception escapes and every
    # pair was visited.
    graph = _FakeGraph(degrees={1: 0, 10: 0}, raises_for={(1, 10)})
    result = _route_between(graph, [1], [10], max_hops=4, max_route_candidate_pairs=100)
    assert result == {"case": "search_bounded", "pairs_tried": 1}


def test_network_overlap_finds_a_real_shared_third_party_neighbor(corpus: Path) -> None:
    # R1's roster (Seed A, Carol, Bob) and R3's roster (Seed C, Dan) don't
    # overlap directly, but Carol and Dan are each other's 1-hop neighbor
    # via R4 -- so Dan is a 1-hop neighbor of R1's roster (through Carol),
    # and Carol is a 1-hop neighbor of R3's roster (through Dan). Neither
    # Carol nor Dan should count as their OWN album's overlap (excluded as
    # each album's own roster), but the network_overlap definition here
    # only counts THIRD PARTIES visible from both sides -- with no third
    # party in this small fixture, the honest answer is zero, not a
    # fabricated one.
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 1, 3))

    assert result["network_overlap"]["count"] == 0
    assert result["network_overlap"]["artist_ids"] == []


def test_scope_tier_comparison_populated_for_two_single_primary_artist_albums(
    corpus: Path,
) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 1, 2))

    scope = result["scope_tier_comparison"]
    assert scope["case"] == "compared"
    assert scope["album_a"]["seed_artist_id"] == SEED_A
    assert scope["album_b"]["seed_artist_id"] == SEED_B


def test_scope_tier_comparison_not_applicable_for_a_various_artists_release(
    corpus: Path,
) -> None:
    with CreditGraph.open(corpus) as graph:
        result = compare_albums(graph, CompareAlbumsRequest(corpus, 1, 5))

    scope = result["scope_tier_comparison"]
    assert scope["case"] == "not_applicable"
    assert "album_b" in scope["reason"]


def test_unresolvable_release_id_raises_compare_error(corpus: Path) -> None:
    with CreditGraph.open(corpus) as graph:
        with pytest.raises(CompareError):
            compare_albums(graph, CompareAlbumsRequest(corpus, 1, 999999))


def test_forbidden_phrase_guard_is_really_wired_in() -> None:
    # Proves the guard function compare.py actually calls is the real one,
    # not just imported and unused -- a directly-injected banned phrase
    # must raise exactly like it does everywhere else in the repo.
    with pytest.raises(ResearchReportError):
        _scan_for_forbidden_phrases("Seed A collaborated with Seed B on this")


def test_run_comparison_and_persist_forwards_performer_only_to_open_graph(
    tmp_path: Path, corpus: Path
) -> None:
    """ADR 0068 / cleanup pass: `request.performer_only` must actually reach
    whatever `open_graph` callable does the opening -- the CLI's default
    `_open_graph_default` and the workbench server's `WorkbenchGraphCache.
    checkout` both take `(root, performer_only)` positionally. A spy that
    still delegates to a real `CreditGraph.open` proves both the VALUE
    forwarded and that the resulting graph genuinely differs."""
    calls: list[bool] = []

    def spying_open(root: Path, performer_only: bool) -> Any:
        calls.append(performer_only)
        return CreditGraph.open(root, performer_only=performer_only)

    request = CompareArtistsRequest(corpus, SEED_A, BOB, performer_only=False)
    run_comparison_and_persist(
        "artists",
        request,
        topic="performer-only-forwarding",
        research_root=tmp_path / "research",
        open_graph=spying_open,
    )
    assert calls == [False]

    default_request = CompareArtistsRequest(corpus, SEED_A, BOB)
    run_comparison_and_persist(
        "artists",
        default_request,
        topic="performer-only-forwarding",
        research_root=tmp_path / "research",
        open_graph=spying_open,
    )
    assert calls == [False, True]


def test_run_comparison_and_persist_records_performer_only_in_the_persisted_request(
    tmp_path: Path, corpus: Path
) -> None:
    import json

    research_root = tmp_path / "research"
    run_comparison_and_persist(
        "artists",
        CompareArtistsRequest(corpus, SEED_A, BOB, performer_only=False),
        topic="performer-only-manifest",
        research_root=research_root,
    )
    runs = list((research_root / "performer-only-manifest" / "runs").iterdir())
    assert len(runs) == 1
    request = json.loads((runs[0] / "request.json").read_text())
    assert request["performer_only"] is False


def test_run_comparison_and_persist_default_open_graph_honors_performer_only(
    tmp_path: Path, corpus: Path
) -> None:
    """No custom `open_graph` at all -- the real default
    (`_open_graph_default`) must still open a genuinely performer-gated
    graph by default, and a genuinely broader one when asked. Bob is
    `release_credit`/"Engineer", credited on release 1 alongside billed
    Seed A (this file's own module docstring): under the performer gate he
    has zero traversable edges at all (his only credit row documents no
    performance), so `find_path` reports no route; opened broader, the
    release_scope edge from Seed A's billing to Bob's extra credit forms,
    and it is a genuine one-hop path."""
    default_result = run_comparison_and_persist(
        "artists",
        CompareArtistsRequest(corpus, SEED_A, BOB),
        topic="default-open-graph-gated",
        research_root=tmp_path / "research",
    )
    assert default_result["comparison"]["route"]["case"] == "no_path_within_bound"

    broad_result = run_comparison_and_persist(
        "artists",
        CompareArtistsRequest(corpus, SEED_A, BOB, performer_only=False),
        topic="default-open-graph-broad",
        research_root=tmp_path / "research",
    )
    broad_route = broad_result["comparison"]["route"]
    assert broad_route["case"] == "found"
    assert len(broad_route["hops"]) == 1
