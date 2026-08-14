from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.pathfinding_graph import (
    pathfinding_graph_failures,
    pathfinding_graph_version,
)

_SNAPSHOT = "20260601"

# Shared, cross-language fixture set (also loaded by apps/web/tests/
# pathfinding-bfs*.spec.ts) -- a malformed case added here is automatically
# exercised against both the Python and TypeScript validators, closing the
# parity gap ADR 0051's revisit trigger names.
_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "pathfinding-graph"


def _load_fixture(name: str) -> Any:
    return json.loads((_FIXTURE_DIR / f"{name}.json").read_text())


_FIXTURE_CATALOG = _load_fixture("catalog")


def _catalog() -> dict[str, Any]:
    albums = [
        {
            "id": "master-1",
            "master_id": None,
            "main_release_id": 1,
            "title": "First Light",
            "artist_id": 100,
            "artist": "Alice",
            "year": 1995,
        },
        {
            "id": "master-2",
            "master_id": None,
            "main_release_id": 2,
            "title": "Second Wave",
            "artist_id": 200,
            "artist": "Bob",
            "year": 1998,
        },
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT),
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-album-catalog 0.1.0",
        "albums": albums,
    }


def _graph() -> dict[str, Any]:
    catalog = _catalog()
    # Node 0 = artist 100, node 1 = artist 200, node 2 = artist 300.
    # Edges (both directions, matching CSR symmetry): 100<->200 (release 1),
    # 100<->300 (release 2).
    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "snapshot_date": _SNAPSHOT,
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Discogs monthly data dump (CC0), one-hop working set.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "node_ids": [100, 200, 300],
        "names": ["Alice", "Bob", "Carol"],
        "offsets": [0, 2, 3, 4],
        "neighbors": [1, 2, 0, 0],
        "evidence_release_ids": [1, 2, 1, 2],
        "edge_role_a": ["Guitar", "Producer", "Bass", "Vocals"],
        "edge_role_b": ["Bass", "Vocals", "Guitar", "Producer"],
    }
    payload["pathfinding_graph_version"] = pathfinding_graph_version(payload, _SNAPSHOT)
    return payload


def test_clean_graph_has_no_failures() -> None:
    assert pathfinding_graph_failures(_graph(), _catalog()) == []


def test_wrong_top_level_type_fails() -> None:
    assert pathfinding_graph_failures("nope", _catalog()) != []
    assert pathfinding_graph_failures(_graph(), "nope") != []


def test_mismatched_catalog_version_is_caught() -> None:
    graph = deepcopy(_graph())
    graph["catalog_version"] = "catalog-v1-wrong"
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("catalog_version" in f for f in failures)


def test_stale_version_is_caught() -> None:
    graph = deepcopy(_graph())
    graph["pathfinding_graph_version"] = "pathfinding-graph-v1-20260601-" + "0" * 12
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("pathfinding_graph_version" in f for f in failures)


def test_unsorted_node_ids_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["node_ids"] = [200, 100, 300]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("sorted" in f for f in failures)


def test_names_wrong_length_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["names"] = ["Alice", "Bob"]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("names" in f for f in failures)


def test_offsets_wrong_length_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["offsets"] = [0, 2, 3]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("offsets" in f for f in failures)


def test_out_of_range_neighbor_index_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["neighbors"] = [1, 99, 0, 0]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("not a valid node index" in f for f in failures)


def test_mismatched_parallel_array_length_is_rejected() -> None:
    graph = deepcopy(_graph())
    graph["edge_role_a"] = ["Guitar"]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("edge_role_a" in f for f in failures)


# --- v2: virtual album-anchor nodes (ADR 0058) ------------------------------

_SENTINEL = "__np_album_anchor__"


def _graph_v2() -> dict[str, Any]:
    """Two catalog albums (master-1/artist 100, master-2/artist 200), one
    real edge between them (release 5), and one virtual anchor per album
    connected to its own credited artist. node_ids sorted:
    [-2 (master-2 anchor), -1 (master-1 anchor), 100, 200]."""
    catalog = _catalog()
    payload: dict[str, Any] = {
        "schema_version": 2,
        "catalog_version": catalog["catalog_version"],
        "snapshot_date": _SNAPSHOT,
        "generated_at": "2026-08-08T00:00:00+00:00",
        "source": "Discogs monthly data dump (CC0), one-hop working set.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "node_ids": [-2, -1, 100, 200],
        "names": ["Second Wave (album anchor)", "First Light (album anchor)", "Alice", "Bob"],
        "offsets": [0, 1, 2, 4, 6],
        "neighbors": [3, 2, 1, 3, 0, 2],
        "evidence_release_ids": [2, 1, 1, 5, 2, 5],
        "edge_role_a": [_SENTINEL, _SENTINEL, "Guitar", "Guitar", "Bass", "Bass"],
        "edge_role_b": ["Bass", "Guitar", _SENTINEL, "Bass", _SENTINEL, "Guitar"],
        "album_virtual_nodes": [
            {"album_id": "master-1", "virtual_artist_id": -1, "main_release_id": 1},
            {"album_id": "master-2", "virtual_artist_id": -2, "main_release_id": 2},
        ],
    }
    payload["pathfinding_graph_version"] = pathfinding_graph_version(payload, _SNAPSHOT)
    return payload


def test_clean_v2_graph_has_no_failures() -> None:
    assert pathfinding_graph_failures(_graph_v2(), _catalog()) == []


def test_v2_version_prefix_is_v2() -> None:
    graph = _graph_v2()
    assert graph["pathfinding_graph_version"].startswith(f"pathfinding-graph-v2-{_SNAPSHOT}-")


def test_v2_missing_album_virtual_nodes_key_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    del graph["album_virtual_nodes"]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("unexpected top-level keys" in f for f in failures)


def test_v2_positive_virtual_artist_id_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    graph["album_virtual_nodes"][0]["virtual_artist_id"] = 1
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("must be a" in f and "negative integer" in f for f in failures)


def test_v2_duplicate_virtual_artist_id_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    graph["album_virtual_nodes"][1]["virtual_artist_id"] = -1
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("duplicate virtual_artist_id" in f for f in failures)


def test_v2_album_id_not_in_catalog_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    graph["album_virtual_nodes"][0]["album_id"] = "master-999"
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("is not in the canonical catalog" in f for f in failures)


def test_v2_virtual_id_missing_from_node_ids_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    graph["album_virtual_nodes"][0]["virtual_artist_id"] = -3
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("is not present in node_ids" in f for f in failures)


def test_v2_sentinel_misuse_on_real_side_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    graph["edge_role_b"][2] = "Not the sentinel"  # slot 2 is (100 -> -1), role_b must be sentinel
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("sentinel placement" in f for f in failures)


def test_v2_sentinel_used_on_a_real_slot_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    graph["edge_role_a"][3] = _SENTINEL  # slot 3 is (100 -> 200), a real-real edge
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("sentinel placement" in f for f in failures)


# --- catalog-coverage / main_release_id agreement (post-#110 correctness
# closeout follow-up) -- the contract (data/contracts/pathfinding-graph-v2.md)
# requires one album_virtual_nodes entry per catalog album, including a
# catalog album with zero in-scope credited contributors, and that each
# entry's main_release_id VALUE agrees with the catalog's own value for that
# album, not merely that it's an integer. Neither direction was previously
# enforced: album_virtual_nodes[i].album_id was only ever checked to resolve
# INTO the catalog, never the reverse (every catalog album resolving OUT to
# an entry), and main_release_id was only ever type-checked. Both gaps were
# confirmed to accept malformed input with zero failures before this fix.


def test_v2_missing_catalog_album_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    del graph["album_virtual_nodes"][1]  # master-2 no longer has any entry at all
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any(
        "missing a virtual node for catalog album" in f and "master-2" in f for f in failures
    )


def test_v2_main_release_id_mismatches_catalog_is_rejected() -> None:
    graph = deepcopy(_graph_v2())
    # Still a real integer -- the pre-existing type check alone would accept
    # this. The catalog's own main_release_id for master-1 is 1.
    graph["album_virtual_nodes"][0]["main_release_id"] = 999
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any(
        "main_release_id" in f and "does not match" in f and "master-1" in f for f in failures
    )


def test_v2_zero_contributor_album_virtual_node_is_accepted() -> None:
    """The contract's own explicit case: an album with zero in-scope
    credited contributors still gets a real, isolated virtual node --
    "never silently dropped" -- and that must be ACCEPTED, not merely
    "removing it is rejected" (the two prior tests). Three catalog albums;
    master-3 (virtual node -3, sorted first) has no membership/neighbors of
    its own -- zero-length CSR slice, offsets[0] == offsets[1] == 0.
    Written out explicitly (not derived by mutating _graph_v2()'s CSR
    arrays in place) because inserting a node shifts every existing
    `neighbors` index by one -- easy to get silently wrong; this literal
    shape was verified directly against pathfinding_graph_failures before
    being written here."""
    catalog = _catalog()
    catalog["albums"].append(
        {
            "id": "master-3",
            "master_id": None,
            "main_release_id": 3,
            "title": "Third Light",
            "artist_id": 300,
            "artist": "Carol",
            "year": 2001,
        }
    )
    graph: dict[str, Any] = {
        "schema_version": 2,
        "catalog_version": catalog["catalog_version"],
        "snapshot_date": _SNAPSHOT,
        "generated_at": "2026-08-08T00:00:00+00:00",
        "source": "Discogs monthly data dump (CC0), one-hop working set.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "node_ids": [-3, -2, -1, 100, 200],
        "names": [
            "Third Light (album anchor)",
            "Second Wave (album anchor)",
            "First Light (album anchor)",
            "Alice",
            "Bob",
        ],
        "offsets": [0, 0, 1, 2, 4, 6],
        "neighbors": [4, 3, 2, 4, 1, 3],
        "evidence_release_ids": [2, 1, 1, 5, 2, 5],
        "edge_role_a": [_SENTINEL, _SENTINEL, "Guitar", "Guitar", "Bass", "Bass"],
        "edge_role_b": ["Bass", "Guitar", _SENTINEL, "Bass", _SENTINEL, "Guitar"],
        "album_virtual_nodes": [
            {"album_id": "master-1", "virtual_artist_id": -1, "main_release_id": 1},
            {"album_id": "master-2", "virtual_artist_id": -2, "main_release_id": 2},
            {"album_id": "master-3", "virtual_artist_id": -3, "main_release_id": 3},
        ],
    }
    graph["pathfinding_graph_version"] = pathfinding_graph_version(graph, _SNAPSHOT)
    assert pathfinding_graph_failures(graph, catalog) == []


# --- shared, cross-language fixture set --------------------------------
# Every file under data/fixtures/pathfinding-graph/ is also loaded by
# apps/web/tests/pathfinding-bfs*.spec.ts against validatePathfindingGraph
# -- these tests prove the Python side agrees on the same files, not just
# on inline-built equivalents.


def test_shared_well_formed_v1_fixture_has_no_failures() -> None:
    graph = _load_fixture("well-formed-v1")
    assert pathfinding_graph_failures(graph, _FIXTURE_CATALOG) == []


def test_shared_well_formed_v2_fixture_has_no_failures() -> None:
    graph = _load_fixture("well-formed-v2")
    assert pathfinding_graph_failures(graph, _FIXTURE_CATALOG) == []


def test_shared_non_monotonic_offsets_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-non-monotonic-offsets")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("non-decreasing" in f for f in failures)


def test_shared_unsorted_node_ids_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-unsorted-node-ids")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("must be sorted" in f for f in failures)


def test_shared_duplicate_node_ids_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-duplicate-node-ids")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("must not contain duplicates" in f for f in failures)


def test_shared_tampered_hash_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-tampered-hash")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("does not match recomputed content" in f for f in failures)


def test_shared_wrong_top_level_keys_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-wrong-top-level-keys")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("unexpected top-level keys" in f for f in failures)


def test_shared_misplaced_sentinel_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-misplaced-sentinel")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("sentinel placement" in f for f in failures)


# --- parity-hardening follow-up (post-#109 correctness closeout) --------
# These close specific gaps found by comparing this validator against
# validatePathfindingGraph line by line: TS was missing nonempty-metadata,
# exact virtual-node keys, and integer-typed id/index/offset checks.


def test_shared_empty_metadata_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-empty-metadata")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("generated_at" in f and "non-empty" in f for f in failures)


def test_truthy_non_string_metadata_is_rejected() -> None:
    # Review follow-up on #110: a truthy non-string (generated_at: 1) used
    # to pass the old truthy-only check even though
    # validatePathfindingGraph's matching TS check requires a real string --
    # letting this pass validate-public-artifacts (Python) while still
    # failing loadPathfindingGraph() at runtime in the browser.
    graph = deepcopy(_graph_v2())
    graph["generated_at"] = 1
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("generated_at" in f and "non-empty" in f for f in failures)


def test_shared_virtual_node_missing_key_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-virtual-node-missing-key")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("must have keys" in f for f in failures)


def test_shared_virtual_node_extra_key_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-virtual-node-extra-key")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("must have keys" in f for f in failures)


def test_shared_fractional_offset_fixture_is_rejected() -> None:
    # Also a crash-safety regression test: a float offset used to reach
    # range() uncaught (TypeError). This fixture reproduces that shape.
    graph = _load_fixture("malformed-fractional-offset")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("offsets must contain only integers" in f for f in failures)


def test_shared_fractional_neighbor_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-fractional-neighbor")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("neighbors must be an array of integers" in f for f in failures)


def test_shared_fractional_main_release_id_fixture_is_rejected() -> None:
    graph = _load_fixture("malformed-fractional-main-release-id")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("main_release_id must be an integer" in f for f in failures)


def test_shared_node_id_wrong_type_fixture_is_rejected() -> None:
    # Also a crash-safety regression test: a str node_id alongside ints used
    # to reach sorted() uncaught (TypeError: '<' not supported).
    graph = _load_fixture("malformed-node-id-wrong-type")
    failures = pathfinding_graph_failures(graph, _FIXTURE_CATALOG)
    assert any("node_ids must contain only integers" in f for f in failures)


# --- Python-local: values that aren't meaningfully shareable JSON fixtures
# (a bare inline payload isolates the case more clearly than a full graph
# fixture would), or that are Python-specific (bool is a subtype of int).


def test_neighbors_containing_a_bool_is_rejected() -> None:
    # bool is a subtype of int in Python -- isinstance(True, int) is True,
    # so this needs its own exclusion the same way virtual_artist_id and
    # main_release_id already have one. Regression test for exactly the
    # Python-only bug the parity investigation found: True silently passed
    # as a valid neighbor index (1) before this fix.
    graph = deepcopy(_graph())
    graph["neighbors"] = [True, 0]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert any("neighbors must be an array of integers" in f for f in failures)


def test_unhashable_node_ids_do_not_crash_the_validator() -> None:
    # A malformed-but-JSON-shaped payload must produce failures, never an
    # uncaught exception. A list-valued node_id used to reach set()
    # uncaught (TypeError: unhashable type: 'list').
    graph = deepcopy(_graph())
    graph["node_ids"] = [[1, 2], [3, 4]]
    graph["names"] = ["A", "B"]
    failures = pathfinding_graph_failures(graph, _catalog())
    assert isinstance(failures, list) and failures
    assert any("node_ids must contain only integers" in f for f in failures)
