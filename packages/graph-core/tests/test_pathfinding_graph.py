from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.graph import CreditGraph
from networked_players_graph_core.pathfinding_graph import (
    ALBUM_ANCHOR_SENTINEL,
    build_pathfinding_graph,
    edge_eligible_membership_artist_ids,
)

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-abc123abc123"


def _credit(
    release_id: int,
    artist_id: int,
    name: str,
    *,
    credit_scope: str = "release_artist",
    track_index: int | None = None,
    role_text: str | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": str(track_index) if track_index is not None else None,
        "track_position": "1" if track_index is not None else None,
        "track_title": "Take" if track_index is not None else None,
        "credit_scope": credit_scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": None,
        "master_id": release_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _co_performer_credits(
    release_id: int, a: tuple[int, str, str], b: tuple[int, str, str]
) -> list[dict[str, Any]]:
    a_id, a_name, a_role = a
    b_id, b_name, b_role = b
    return [
        _credit(release_id, a_id, a_name, credit_scope="release_artist"),
        _credit(
            release_id, a_id, a_name, credit_scope="track_artist", track_index=0, role_text=a_role
        ),
        _credit(release_id, b_id, b_name, credit_scope="release_artist"),
        _credit(
            release_id, b_id, b_name, credit_scope="track_artist", track_index=0, role_text=b_role
        ),
    ]


@pytest.fixture
def onehop_dataset(tmp_path: Path) -> Path:
    """Alice (seed artist, album master-1) co-performs with Bob (release 1)
    and with Carol (release 2) -- Bob and Carol are one hop out from the
    catalog's only seed artist and must appear in the pathfinding graph."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1"), _release(2, "R2")]
    credits = [
        *_co_performer_credits(1, (100, "Alice", "Guitar"), (200, "Bob", "Bass")),
        *_co_performer_credits(2, (100, "Alice", "Producer"), (300, "Carol", "Vocals")),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


def _catalog(*, main_release_id: int = 1) -> dict[str, Any]:
    return {
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "albums": [
            {
                "id": "master-1",
                "title": "First Light",
                "artist_id": 100,
                "main_release_id": main_release_id,
                "year": 1995,
            }
        ],
    }


def _membership(
    *, main_release_id: int = 1, credits: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """A minimal album-credit-membership artifact naming Alice as the sole
    credited contributor on master-1's release, unless `credits` overrides
    it -- matches the real Slice 2 artifact shape closely enough for this
    module's own tests (full contract coverage lives in
    test_album_credit_membership.py)."""
    default_credits = [
        {
            "artist_id": 100,
            "name": "Alice",
            "anv": None,
            "role_text": None,
            "credit_scope": "release_artist",
            "track_position": None,
            "track_title": None,
        }
    ]
    return {
        "schema_version": 1,
        "catalog_version": _CATALOG_VERSION,
        "album_credit_membership_version": "album-credit-membership-v1-test",
        "generated_at": "2026-08-08T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "albums": [
            {
                "album_id": "master-1",
                "main_release_id": main_release_id,
                "credits": credits if credits is not None else default_credits,
            }
        ],
    }


def _by_pair(payload: dict[str, Any]) -> dict[tuple[int, int], tuple[str, str]]:
    node_ids = payload["node_ids"]
    result: dict[tuple[int, int], tuple[str, str]] = {}
    for node_index in range(len(node_ids)):
        start, end = payload["offsets"][node_index], payload["offsets"][node_index + 1]
        artist_a_id = node_ids[node_index]
        for slot in range(start, end):
            neighbor_index = payload["neighbors"][slot]
            artist_b_id = node_ids[neighbor_index]
            result[(artist_a_id, artist_b_id)] = (
                payload["edge_role_a"][slot],
                payload["edge_role_b"][slot],
            )
    return result


def test_pathfinding_graph_includes_the_1hop_neighborhood(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-03T00:00:00+00:00",
        )

    real_node_ids = {n for n in payload["node_ids"] if n > 0}
    assert real_node_ids == {100, 200, 300}
    name_by_id = {
        node_id: name
        for node_id, name in zip(payload["node_ids"], payload["names"], strict=True)
        if node_id > 0
    }
    assert name_by_id == {100: "Alice", 200: "Bob", 300: "Carol"}


def test_edge_roles_carry_real_role_text_for_both_endpoints(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-03T00:00:00+00:00",
        )

    by_pair = _by_pair(payload)
    assert by_pair[(100, 200)] == ("Guitar", "Bass")
    assert by_pair[(200, 100)] == ("Bass", "Guitar")
    assert by_pair[(100, 300)] == ("Producer", "Vocals")
    assert by_pair[(300, 100)] == ("Vocals", "Producer")


@pytest.fixture
def two_role_dataset(tmp_path: Path) -> Path:
    """Alice holds two distinct track_artist role credits on release 1
    (Guitar on one track, Keys on another) alongside Bob's single Bass
    credit -- the edge role text for (100, 200) must join both of Alice's
    roles, not silently keep only the first."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1")]
    credits = [
        _credit(1, 100, "Alice", credit_scope="release_artist"),
        _credit(1, 100, "Alice", credit_scope="track_artist", track_index=0, role_text="Guitar"),
        _credit(1, 100, "Alice", credit_scope="track_artist", track_index=1, role_text="Keys"),
        _credit(1, 200, "Bob", credit_scope="release_artist"),
        _credit(1, 200, "Bob", credit_scope="track_artist", track_index=0, role_text="Bass"),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


def test_edge_role_joins_multiple_distinct_roles(two_role_dataset: Path) -> None:
    with CreditGraph.open(two_role_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )

    by_pair = _by_pair(payload)
    assert by_pair[(100, 200)] == ("Guitar, Keys", "Bass")
    assert by_pair[(200, 100)] == ("Bass", "Guitar, Keys")


def test_edge_role_join_produces_clean_comma_components(two_role_dataset: Path) -> None:
    """Direct regression test for a real caught defect: joining with any
    separator other than ", " produces a merged component (e.g. "Guitar;
    Producer") that fails the frontend role-taxonomy classifiers' exact-
    match-per-comma-component parsing (apps/web/src/game/roleTaxonomy.ts's
    `matchesAnyComponent`, and role_taxonomy.py's own `classify_role`,
    which both split strictly on "," and require an exact token match per
    component) -- a single-token role adjacent to another role with no
    internal comma of its own silently stopped classifying at all. This
    mirrors that exact shape (single-token "Guitar" next to single-token
    "Keys") and asserts the join produces clean, independently-parseable
    comma components, not a fused string."""
    with CreditGraph.open(two_role_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )

    node_ids = payload["node_ids"]
    alice_index = node_ids.index(100)
    start, end = payload["offsets"][alice_index], payload["offsets"][alice_index + 1]
    role_for_bob = next(
        payload["edge_role_a"][slot]
        for slot in range(start, end)
        if node_ids[payload["neighbors"][slot]] == 200
    )
    components = [c.strip().lower() for c in role_for_bob.split(",")]
    assert components == ["guitar", "keys"]


@pytest.fixture
def many_role_dataset(tmp_path: Path) -> Path:
    """Alice holds 30 distinct, verbose role credits on release 1 -- a real
    corpus measurement found joining every distinct role unbounded can
    reach 2,639 characters for a busy multi-track release. The joined
    result must stay bounded (`_MAX_JOINED_ROLE_LEN`), not grow without
    limit."""
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1")]
    credits = [_credit(1, 100, "Alice", credit_scope="release_artist")]
    for i in range(30):
        credits.append(
            _credit(
                1,
                100,
                "Alice",
                credit_scope="track_artist",
                track_index=i,
                role_text=f"Producer, Piano, Backing Vocals [Variant {i}]",
            )
        )
    credits.append(_credit(1, 200, "Bob", credit_scope="release_artist"))
    credits.append(
        _credit(1, 200, "Bob", credit_scope="track_artist", track_index=0, role_text="Bass")
    )
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


def test_edge_role_join_stays_bounded(many_role_dataset: Path) -> None:
    with CreditGraph.open(many_role_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )

    node_ids = payload["node_ids"]
    alice_index = node_ids.index(100)
    start, end = payload["offsets"][alice_index], payload["offsets"][alice_index + 1]
    role_for_bob = next(
        payload["edge_role_a"][slot]
        for slot in range(start, end)
        if node_ids[payload["neighbors"][slot]] == 200
    )
    assert len(role_for_bob) <= 201  # _MAX_JOINED_ROLE_LEN + the trailing ellipsis character
    assert role_for_bob.endswith("…")


def test_top_level_shape_and_version(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-03T00:00:00+00:00",
        )
    assert payload["schema_version"] == 3
    assert payload["catalog_version"] == _CATALOG_VERSION
    assert payload["graph_policy_version"] == 1
    assert payload["pathfinding_graph_version"].startswith(f"pathfinding-graph-v3-{_SNAPSHOT}-")


def test_deterministic_across_repeated_builds(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        first = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-03T00:00:00+00:00",
        )
    with CreditGraph.open(onehop_dataset) as graph:
        second = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-03T00:00:00+00:00",
        )
    assert first == second


def test_no_albums_raises() -> None:
    empty_catalog = {"catalog_version": _CATALOG_VERSION, "snapshot_date": _SNAPSHOT, "albums": []}
    with pytest.raises(ValueError, match="no albums"):
        # A real graph isn't even needed -- this must fail before querying it.
        build_pathfinding_graph(
            None,  # type: ignore[arg-type]
            empty_catalog,
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-03T00:00:00+00:00",
        )


# --- virtual album-anchor nodes (ADR 0058) ----------------------------------


def test_virtual_node_id_is_negative_and_disjoint_from_real_ids(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )
    virtual_node = payload["album_virtual_nodes"][0]
    assert virtual_node["virtual_artist_id"] < 0
    assert virtual_node["virtual_artist_id"] not in {n for n in payload["node_ids"] if n > 0}
    assert virtual_node["virtual_artist_id"] in payload["node_ids"]


def test_virtual_node_connects_to_every_real_credited_contributor(onehop_dataset: Path) -> None:
    """master-1's membership credits Alice (100) and Bob (200) -- both are
    real nodes in this fixture's ego network, so the virtual anchor's
    neighbors must be exactly {100, 200}, matching the membership list
    exactly (Carol, 300, is not credited on master-1 and must not appear)."""
    membership = _membership(
        credits=[
            {
                "artist_id": 100,
                "name": "Alice",
                "anv": None,
                "role_text": "Producer",
                "credit_scope": "release_artist",
                "track_position": None,
                "track_title": None,
            },
            {
                "artist_id": 200,
                "name": "Bob",
                "anv": None,
                "role_text": "Bass",
                "credit_scope": "release_artist",
                "track_position": None,
                "track_title": None,
            },
        ]
    )
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            membership,
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )
    virtual_id = payload["album_virtual_nodes"][0]["virtual_artist_id"]
    node_ids = payload["node_ids"]
    virtual_index = node_ids.index(virtual_id)
    start, end = payload["offsets"][virtual_index], payload["offsets"][virtual_index + 1]
    neighbor_ids = {node_ids[payload["neighbors"][slot]] for slot in range(start, end)}
    assert neighbor_ids == {100, 200}


def test_packaging_only_membership_credit_creates_no_anchor_edge(onehop_dataset: Path) -> None:
    """A contributor whose ONLY credit on the album is non-collaborative by
    `graph.py`'s own denylist must not become a routing hop.

    This is the real Discovery -> The Joshua Tree defect, reduced: `Alex And
    Martin` were credited `Design Concept, Art Direction` on Discovery -- every
    component of which `graph.py` already refuses to build a contributor edge
    from -- and the album anchor made them a first-class hop anyway, so the
    recommended route between two records ran through a sleeve designer who
    also directed a U2 video."""
    membership = _membership(
        credits=[
            {
                "artist_id": 100,
                "name": "Alice",
                "anv": None,
                "role_text": "Producer",
                "credit_scope": "release_artist",
                "track_position": None,
                "track_title": None,
            },
            {
                "artist_id": 200,
                "name": "Bob",
                "anv": None,
                "role_text": "Design Concept, Art Direction",
                "credit_scope": "release_credit",
                "track_position": None,
                "track_title": None,
            },
        ]
    )
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            membership,
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )
    virtual_id = payload["album_virtual_nodes"][0]["virtual_artist_id"]
    node_ids = payload["node_ids"]
    virtual_index = node_ids.index(virtual_id)
    start, end = payload["offsets"][virtual_index], payload["offsets"][virtual_index + 1]
    neighbor_ids = {node_ids[payload["neighbors"][slot]] for slot in range(start, end)}
    assert neighbor_ids == {100}


def test_a_billed_artist_keeps_its_anchor_edge_despite_a_non_collaborative_role(
    onehop_dataset: Path,
) -> None:
    """Eligibility is decided per credit, never on the joined display role.

    Measured on the real artifacts: nine catalog albums join to a display role
    of `Written-By`/`Composed By`/`Songwriter` for their OWN billed artist. If
    the filter read that joined string it would detach Bob Dylan from `Blood On
    The Tracks`. A billed artist's `release_artist` credit carries a NULL role,
    which is always edge-eligible (the same rule `credit_edges_sql` applies),
    so evaluating each credit separately keeps them."""
    membership = _membership(
        credits=[
            {
                "artist_id": 100,
                "name": "Alice",
                "anv": None,
                "role_text": None,
                "credit_scope": "release_artist",
                "track_position": None,
                "track_title": None,
            },
            {
                "artist_id": 100,
                "name": "Alice",
                "anv": None,
                "role_text": "Written-By",
                "credit_scope": "release_credit",
                "track_position": None,
                "track_title": None,
            },
        ]
    )
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            membership,
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )
    virtual_id = payload["album_virtual_nodes"][0]["virtual_artist_id"]
    node_ids = payload["node_ids"]
    virtual_index = node_ids.index(virtual_id)
    start, end = payload["offsets"][virtual_index], payload["offsets"][virtual_index + 1]
    neighbor_ids = {node_ids[payload["neighbors"][slot]] for slot in range(start, end)}
    assert neighbor_ids == {100}


def test_edge_eligible_membership_artist_ids_keeps_an_artist_with_any_eligible_credit() -> None:
    membership = {
        "credits": [
            {"artist_id": 1, "role_text": "Photography By", "credit_scope": "release_credit"},
            {"artist_id": 1, "role_text": "Bass", "credit_scope": "release_credit"},
            {"artist_id": 2, "role_text": "Art Direction", "credit_scope": "release_credit"},
            {"artist_id": 2, "role_text": "Design", "credit_scope": "release_credit"},
            # A bare NULL-role billing (the primary artist's own record) --
            # always kept, regardless of role text, because it is billing
            # scope (ADR 0068), the same rule `credit_edges_sql` uses.
            {"artist_id": 3, "role_text": None, "credit_scope": "release_artist"},
            {"artist_id": 4, "role_text": "Film Director", "credit_scope": "release_credit"},
        ]
    }
    assert edge_eligible_membership_artist_ids(membership) == {1, 3}


def test_edge_eligible_membership_artist_ids_excludes_quotation_role_text() -> None:
    """Round-1 Codex review finding on PR #204: `is_performer_role` alone
    strips `Performer [Sample]`'s bracket down to `performer`, a real
    performer token -- it has no quotation check, unlike
    `edge_ineligible_role` (`credit_edges_sql`'s universal entry gate,
    which real `_QUOTATION_ROLE_PATTERN`/`_BARE_QUOTATION_ROLES` logic
    correctly excludes). An artist credited ONLY via a sample quotation
    must not become an album anchor."""
    membership = {
        "credits": [
            {"artist_id": 1, "role_text": "Performer [Sample]", "credit_scope": "release_credit"},
            {
                "artist_id": 2,
                "role_text": "Featuring [Samples From]",
                "credit_scope": "track_credit",
            },
            {"artist_id": 3, "role_text": "Samples", "credit_scope": "release_credit"},
            # A real, non-quotation performer credit still qualifies.
            {"artist_id": 4, "role_text": "Guitar", "credit_scope": "release_credit"},
        ]
    }
    assert edge_eligible_membership_artist_ids(membership) == {4}


def test_virtual_edge_role_is_sentinel_on_virtual_side_and_membership_role_on_real_side(
    onehop_dataset: Path,
) -> None:
    membership = _membership(
        credits=[
            {
                "artist_id": 100,
                "name": "Alice",
                "anv": None,
                "role_text": "Producer",
                "credit_scope": "release_artist",
                "track_position": None,
                "track_title": None,
            }
        ]
    )
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            membership,
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )
    virtual_id = payload["album_virtual_nodes"][0]["virtual_artist_id"]
    by_pair = _by_pair(payload)
    assert by_pair[(virtual_id, 100)] == (ALBUM_ANCHOR_SENTINEL, "Producer")
    assert by_pair[(100, virtual_id)] == ("Producer", ALBUM_ANCHOR_SENTINEL)


def test_album_with_no_in_scope_credited_contributors_gets_isolated_virtual_node(
    onehop_dataset: Path,
) -> None:
    """An album whose credited contributors are entirely outside this
    ego network (or has none) must not crash the build -- its virtual node
    still exists, just with zero neighbors, so a search against it is a
    real, confirmed "no-path," never a crash or "unknown-album."""
    membership = _membership(credits=[])
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            membership,
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )
    virtual_id = payload["album_virtual_nodes"][0]["virtual_artist_id"]
    node_ids = payload["node_ids"]
    assert virtual_id in node_ids
    virtual_index = node_ids.index(virtual_id)
    assert payload["offsets"][virtual_index] == payload["offsets"][virtual_index + 1]


def test_album_virtual_nodes_field_shape(onehop_dataset: Path) -> None:
    with CreditGraph.open(onehop_dataset) as graph:
        payload = build_pathfinding_graph(
            graph,
            _catalog(),
            _membership(),
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-07T00:00:00+00:00",
        )
    assert payload["album_virtual_nodes"] == [
        {"album_id": "master-1", "virtual_artist_id": -1, "main_release_id": 1}
    ]


# --- Canonical display names (ADR 0059) ---------------------------------


@pytest.fixture
def multi_spelling_dataset(tmp_path: Path) -> Path:
    """Bob is credited three times with two spellings.

    `linked_credits` holds one row per CREDIT, so an artist carries as many
    spellings as contributors typed. Release 1 spells him "bob"; releases 2
    and 3 spell him "Bob". The lowercase spelling is on the LOWEST release
    id, which is what the previous `SELECT DISTINCT` + `setdefault` tended
    to surface -- so this fixture fails loudly if the old behaviour returns.
    """
    from conftest import write_synthetic_dataset

    releases = [_release(1, "R1"), _release(2, "R2"), _release(3, "R3")]
    credits = [
        *_co_performer_credits(1, (100, "Alice", "Guitar"), (200, "bob", "Bass")),
        *_co_performer_credits(2, (100, "Alice", "Guitar"), (200, "Bob", "Bass")),
        *_co_performer_credits(3, (100, "Alice", "Guitar"), (200, "Bob", "Bass")),
    ]
    return write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}", release_rows=releases, credit_rows=credits
    )


def _name_of(payload: dict[str, Any], artist_id: int) -> str:
    return str(payload["names"][payload["node_ids"].index(artist_id)])


def _build(dataset: Path, catalog: dict[str, Any], membership: dict[str, Any]) -> dict[str, Any]:
    with CreditGraph.open(dataset) as graph:
        return build_pathfinding_graph(
            graph,
            catalog,
            membership,
            snapshot_date=_SNAPSHOT,
            generated_at="2026-08-14T00:00:00+00:00",
        )


def test_the_most_credited_spelling_wins(multi_spelling_dataset: Path) -> None:
    payload = _build(multi_spelling_dataset, _catalog(), _membership())
    assert _name_of(payload, 200) == "Bob"


@pytest.mark.parametrize(
    "spelling",
    ["will.i.am", "deadmau5", "k.d. lang", "P!nk", "blink-182", "U2", "THE KLF", "µ-Ziq"],
)
def test_unconventional_spellings_survive_untransformed(tmp_path: Path, spelling: str) -> None:
    """The selection never TRANSFORMS the source string. Generic
    title-casing is exactly what would corrupt every one of these, which is
    why the fix is "pick the most-credited row", not "normalize"."""
    from conftest import write_synthetic_dataset

    dataset = write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}",
        release_rows=[_release(1, "R1")],
        credit_rows=_co_performer_credits(1, (100, "Alice", "Guitar"), (200, spelling, "Bass")),
    )
    payload = _build(dataset, _catalog(), _membership())
    assert _name_of(payload, 200) == spelling


def test_a_tie_is_broken_by_name_so_builds_are_reproducible(tmp_path: Path) -> None:
    """Two spellings, one credit each. Without a tiebreak DuckDB is free to
    return either, and two builds of one dataset could disagree -- which
    would change `pathfinding_graph_version` for no real reason."""
    from conftest import write_synthetic_dataset

    dataset = write_synthetic_dataset(
        tmp_path / f"snapshot={_SNAPSHOT}",
        release_rows=[_release(1, "R1"), _release(2, "R2")],
        credit_rows=[
            *_co_performer_credits(1, (100, "Alice", "Guitar"), (200, "Zeta", "Bass")),
            *_co_performer_credits(2, (100, "Alice", "Guitar"), (200, "Alpha", "Bass")),
        ],
    )
    names = {_name_of(_build(dataset, _catalog(), _membership()), 200) for _ in range(3)}
    assert names == {"Alpha"}
