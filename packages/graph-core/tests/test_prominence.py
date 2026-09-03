from __future__ import annotations

from typing import Any

import pytest

from networked_players_graph_core.prominence import build_prominence, prominence_version

_SNAPSHOT = "20260601"
_CATALOG_VERSION = "catalog-v1-20260601-test"
_SENTINEL = "__np_album_anchor__"


def _graph(*, schema_version: int = 3) -> dict[str, Any]:
    """Two catalog albums (Album A / -1, Album B / -2), each with one direct
    credited contributor (Alice/100 on A, Bob/200 on B), plus a real
    Alice<->Bob collaboration on a third, non-catalog release (99). This is
    the smallest graph with a genuine 2-hop-only album relationship: Alice
    is NOT directly on Album B, but her collaborator Bob is -- so Album B
    is exactly Alice's `albums_2hop`, and symmetrically Album A is Bob's.

    node_ids sorted: [-2 (Album B), -1 (Album A), 100 (Alice), 200 (Bob)]."""
    node_ids = [-2, -1, 100, 200]
    names = ["Album B (album anchor)", "Album A (album anchor)", "Alice", "Bob"]
    offsets = [0, 1, 2, 4, 6]
    neighbors = [3, 2, 1, 3, 0, 2]
    evidence_release_ids = [20, 10, 10, 99, 20, 99]
    edge_role_a = [_SENTINEL, _SENTINEL, "Producer", "Guitar", "Engineer", "Bass"]
    edge_role_b = ["Engineer", "Producer", _SENTINEL, "Bass", _SENTINEL, "Guitar"]
    album_virtual_nodes = [
        {"album_id": "album-a", "virtual_artist_id": -1, "main_release_id": 10},
        {"album_id": "album-b", "virtual_artist_id": -2, "main_release_id": 20},
    ]

    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "catalog_version": _CATALOG_VERSION,
        "snapshot_date": _SNAPSHOT,
        "generated_at": "2026-09-03T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "node_ids": node_ids,
        "names": names,
        "offsets": offsets,
        "neighbors": neighbors,
        "evidence_release_ids": evidence_release_ids,
        "graph_policy_version": 1,
        "album_virtual_nodes": album_virtual_nodes,
    }

    if schema_version >= 4:
        roles: list[str] = []
        role_index: dict[str, int] = {}

        def rid(text: str) -> int:
            if text not in role_index:
                role_index[text] = len(roles)
                roles.append(text)
            return role_index[text]

        payload["roles"] = roles
        payload["edge_role_a"] = [rid(t) for t in edge_role_a]
        payload["edge_role_b"] = [rid(t) for t in edge_role_b]
    else:
        payload["edge_role_a"] = edge_role_a
        payload["edge_role_b"] = edge_role_b

    payload["pathfinding_graph_version"] = f"pathfinding-graph-v{schema_version}-{_SNAPSHOT}-test"
    return payload


def _registry() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "catalog_version": _CATALOG_VERSION,
        "generated_at": "2026-09-03T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "release_ids": [10, 20, 99],
        "years": [2000, 2010, 2005],
    }


def _by_node_id(payload: dict[str, Any], field: str) -> dict[int, Any]:
    return dict(zip(payload["node_ids"], payload[field], strict=True))


def test_hand_verified_two_hop_bridge_v3() -> None:
    payload = build_prominence(
        pathfinding_graph=_graph(schema_version=3),
        evidence_release_registry=_registry(),
        generated_at="2026-09-03T00:00:00+00:00",
    )

    degree = _by_node_id(payload, "degree")
    albums_1hop = _by_node_id(payload, "albums_1hop")
    albums_2hop = _by_node_id(payload, "albums_2hop")
    evidence_releases = _by_node_id(payload, "evidence_releases")
    role_diversity = _by_node_id(payload, "role_diversity")
    first_year = _by_node_id(payload, "first_year")
    last_year = _by_node_id(payload, "last_year")
    rank = _by_node_id(payload, "rank")

    # Alice (100): 1 album directly (A), reaches Album B only via Bob.
    assert degree[100] == 2
    assert albums_1hop[100] == 1
    assert albums_2hop[100] == 1
    assert evidence_releases[100] == 2  # releases 10, 99
    assert role_diversity[100] == 2  # Production (Producer), Strings (Guitar)
    assert first_year[100] == 2000
    assert last_year[100] == 2005
    assert rank[100] == 50 * 1 + 50 * 5 + 10 * 1 + 1 * 2 + 1 * 2  # == 314

    # Bob (200): symmetric to Alice, reaches Album A only via Alice.
    assert degree[200] == 2
    assert albums_1hop[200] == 1
    assert albums_2hop[200] == 1
    assert evidence_releases[200] == 2  # releases 20, 99
    assert role_diversity[200] == 2  # Engineering (Engineer), Strings (Bass)
    assert first_year[200] == 2005
    assert last_year[200] == 2010
    assert rank[200] == 314

    # Virtual album anchors: real degree (a true CSR fact), every other
    # field a zero/null placeholder -- never themselves ranked as a neighbor.
    assert degree[-1] == 1
    assert degree[-2] == 1
    for anchor_id in (-1, -2):
        assert albums_1hop[anchor_id] == 0
        assert albums_2hop[anchor_id] == 0
        assert evidence_releases[anchor_id] == 0
        assert role_diversity[anchor_id] == 0
        assert first_year[anchor_id] is None
        assert last_year[anchor_id] is None
        assert rank[anchor_id] == 0


def test_v4_dictionary_encoded_roles_produce_identical_result() -> None:
    """Same real content as the v3 fixture, dictionary-encoded (ADR 0071) --
    proves this module decodes v4's role indices correctly rather than
    accidentally treating an index as role text."""
    v3 = build_prominence(
        pathfinding_graph=_graph(schema_version=3),
        evidence_release_registry=_registry(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    v4 = build_prominence(
        pathfinding_graph=_graph(schema_version=4),
        evidence_release_registry=_registry(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    for field in (
        "degree",
        "albums_1hop",
        "albums_2hop",
        "evidence_releases",
        "role_diversity",
        "first_year",
        "last_year",
        "rank",
    ):
        assert v3[field] == v4[field], field


def test_node_ids_and_pathfinding_graph_version_are_pinned() -> None:
    graph = _graph()
    payload = build_prominence(
        pathfinding_graph=graph,
        evidence_release_registry=_registry(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    assert payload["node_ids"] == graph["node_ids"]
    assert payload["pathfinding_graph_version"] == graph["pathfinding_graph_version"]
    assert payload["catalog_version"] == _CATALOG_VERSION


def test_prominence_version_matches_recomputation() -> None:
    payload = build_prominence(
        pathfinding_graph=_graph(),
        evidence_release_registry=_registry(),
        generated_at="2026-09-03T00:00:00+00:00",
    )
    assert payload["prominence_version"] == prominence_version(payload, _SNAPSHOT)
    assert payload["prominence_version"].startswith(f"prominence-v1-{_SNAPSHOT}-")


def test_catalog_version_mismatch_raises() -> None:
    registry = _registry()
    registry["catalog_version"] = "catalog-v1-20260601-different"
    with pytest.raises(ValueError, match="catalog_version"):
        build_prominence(
            pathfinding_graph=_graph(),
            evidence_release_registry=registry,
            generated_at="2026-09-03T00:00:00+00:00",
        )


def test_no_known_evidence_years_leaves_first_last_year_null() -> None:
    registry = _registry()
    registry["years"] = [None, None, None]
    payload = build_prominence(
        pathfinding_graph=_graph(),
        evidence_release_registry=registry,
        generated_at="2026-09-03T00:00:00+00:00",
    )
    first_year = _by_node_id(payload, "first_year")
    last_year = _by_node_id(payload, "last_year")
    rank = _by_node_id(payload, "rank")
    assert first_year[100] is None
    assert last_year[100] is None
    # decade_span falls back to 0 when no year is known -- rank still
    # reflects the other real signals, never crashes on missing years.
    assert rank[100] == 50 * 1 + 50 * 0 + 10 * 1 + 1 * 2 + 1 * 2
