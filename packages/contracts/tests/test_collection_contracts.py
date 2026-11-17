"""Collection contract (ADR 0074): synthetic fixtures only."""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_contracts.collection import (
    MAX_SITE_HOPS,
    MAX_VIA,
    collection_failures,
    collection_version,
    collections_failures,
    load_collections_directory,
    url_failures,
)
from networked_players_contracts.public_artifacts import PUBLIC_ARTIFACT_GROUPS

CATALOG_VERSION = "catalog-v1-test-aaaaaaaaaaaa"
GRAPH_VERSION = "pathfinding-graph-v4-test-bbbbbbbbbbbb"

# Albums master-1..master-5 (anchors -1..-5) and performers 10..14.
ANCHOR_PERFORMERS = {
    1: [10, 11],
    2: [11, 12],
    3: [12, 13],
    4: [10, 13],
    5: [13, 14],
}
# Undirected performer edges -> evidence release id.
PERFORMER_EDGES = {(10, 11): 1001, (11, 12): 1002, (12, 13): 1003, (13, 14): 1004}


def make_graph(
    edges: dict[tuple[int, int], int] | None = None,
    anchors: dict[int, list[int]] | None = None,
    names: dict[int, str] | None = None,
) -> dict[str, Any]:
    edges = PERFORMER_EDGES if edges is None else edges
    anchors = ANCHOR_PERFORMERS if anchors is None else anchors
    performers = sorted({p for ps in anchors.values() for p in ps} | {n for e in edges for n in e})
    node_ids = sorted([-n for n in anchors] + performers)
    adjacency: dict[int, list[tuple[int, int]]] = {n: [] for n in node_ids}
    for album, album_performers in anchors.items():
        for p in album_performers:
            adjacency[-album].append((p, 500 + album))
            adjacency[p].append((-album, 500 + album))
    for (a, b), release in edges.items():
        adjacency[a].append((b, release))
        adjacency[b].append((a, release))
    index = {n: i for i, n in enumerate(node_ids)}
    offsets = [0]
    neighbors: list[int] = []
    evidence: list[int] = []
    for n in node_ids:
        for other, release in sorted(adjacency[n], key=lambda item: index[item[0]]):
            neighbors.append(index[other])
            evidence.append(release)
        offsets.append(len(neighbors))
    names = names or {}
    return {
        "schema_version": 4,
        "pathfinding_graph_version": GRAPH_VERSION,
        "node_ids": node_ids,
        "names": [f"Anchor {-n}" if n < 0 else names.get(n, f"Player {n}") for n in node_ids],
        "offsets": offsets,
        "neighbors": neighbors,
        "evidence_release_ids": evidence,
        "album_virtual_nodes": [
            {"album_id": f"master-{n}", "virtual_artist_id": -n, "main_release_id": 500 + n}
            for n in anchors
        ],
    }


def make_catalog(albums: int = 5) -> dict[str, Any]:
    return {
        "catalog_version": CATALOG_VERSION,
        "albums": [
            {"id": f"master-{n}", "artist_id": 100 + (n % 4), "artist": f"Artist {n % 4}"}
            for n in range(1, albums + 1)
        ],
    }


def make_collection() -> dict[str, Any]:
    collection: dict[str, Any] = {
        "schema_version": 1,
        "collection_id": "synthetic-bridge",
        "title": "Synthetic Bridge",
        "intro": "A made-up set of records for tests.",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "records": ["master-1", "master-2", "master-3", "master-4"],
        "bridge_players": [
            {"artist_id": 10, "name": "Player 10", "records": ["master-1", "master-4"]},
            {"artist_id": 11, "name": "Player 11", "records": ["master-1", "master-2"]},
        ],
        "journey": [
            {
                "from_record": "master-1",
                "to_record": "master-3",
                "via": [11, 12],
                "via_names": ["Player 11", "Player 12"],
                "evidence_release_ids": [1002],
            }
        ],
        "provenance": {
            "inputs": {"catalog": CATALOG_VERSION, "pathfinding_graph": GRAPH_VERSION},
            "collection_version": "",
        },
    }
    return restamp(collection)


def restamp(collection: dict[str, Any]) -> dict[str, Any]:
    collection["provenance"]["collection_version"] = collection_version(collection)
    return collection


def failures(collection: Any, graph: Any = None, catalog: Any = None) -> str:
    return " | ".join(
        collection_failures(
            collection, catalog or make_catalog(), graph if graph is not None else make_graph()
        )
    )


def test_valid_collection_passes() -> None:
    assert collection_failures(make_collection(), make_catalog(), make_graph()) == []


def test_record_not_in_catalog() -> None:
    c = make_collection()
    c["records"][3] = "master-99"
    assert "record 'master-99' is not in the catalog" in failures(restamp(c))


def test_too_few_records_and_artists() -> None:
    c = make_collection()
    c["records"] = c["records"][:3]
    assert "must hold 4..24 albums" in failures(restamp(c))
    catalog = make_catalog()
    for album in catalog["albums"]:
        album["artist_id"] = 7
    assert "at least 3 distinct primary artists" in failures(make_collection(), catalog=catalog)


def test_bridge_player_not_adjacent() -> None:
    c = make_collection()
    c["bridge_players"][0]["records"] = ["master-1", "master-2"]  # 10 is not on master-2
    assert "not adjacent to record 'master-2'" in failures(restamp(c))


# ---- major 1: one artist's own albums are not a bridge


def same_artist_catalog() -> dict[str, Any]:
    catalog = make_catalog()
    # master-1 and master-4 share a primary artist; 2, 3, 5 are distinct others.
    for album in catalog["albums"]:
        album["artist_id"] = {1: 7, 4: 7, 2: 8, 3: 9, 5: 10}[int(album["id"].split("-")[1])]
    return catalog


def test_bridge_players_on_one_artists_records_only_is_refused() -> None:
    # player 10 is credited on master-1 and master-4 only, both by artist 7.
    text = failures(make_collection(), catalog=same_artist_catalog())
    assert "bridge_players[0] ('Player 10')" in text
    assert "must span at least 2 distinct primary artists" in text


def test_primary_artist_may_bridge_when_records_span_artists() -> None:
    # Player 11 is credited on master-1 (artist 7) and master-2 (artist 8): allowed.
    text = failures(make_collection(), catalog=same_artist_catalog())
    assert "bridge_players[1]" not in text


def test_journey_hop_between_same_artist_records_is_refused() -> None:
    c = make_collection()
    c["journey"] = [
        {
            "from_record": "master-1",
            "to_record": "master-4",
            "via": [10],
            "via_names": ["Player 10"],
            "evidence_release_ids": [],
        }
    ]
    text = failures(restamp(c), catalog=same_artist_catalog())
    assert "journey hop 1 (master-1 -> master-4): both records have the same primary artist" in text


def test_playable_pair_between_same_artist_records_is_refused() -> None:
    c = make_collection()
    c["playable_cohort"] = {
        "schema_version": 2,
        "route_policy": "shortest-first-found-v1",
        "pairs": [
            {
                "record_a": "master-1",
                "record_b": "master-4",
                "hop_count": 0,
                "via": [10],
                "via_names": ["Player 10"],
                "evidence_release_ids": [],
            }
        ],
    }
    assert "same primary artist" in failures(restamp(c), catalog=same_artist_catalog())


def test_journey_hop_without_edge() -> None:
    c = make_collection()
    c["journey"][0]["via"] = [10, 12]
    c["journey"][0]["via_names"] = ["Player 10", "Player 12"]
    assert "no edge between performers 10 and 12" in failures(restamp(c))


def test_evidence_must_equal_the_graphs() -> None:
    c = make_collection()
    c["journey"][0]["evidence_release_ids"] = [9999]
    assert "differs from the graph's evidence release 1002" in failures(restamp(c))


def test_private_fields_are_refused() -> None:
    for key in ("notes", "reviewer", "reviewed_by", "rejected", "working_title", "x_private"):
        c = make_collection()
        c[key] = "secret"
        assert f"private field '$.{key}'" in failures(c)
    # Nested at any depth: only the denylist produces this message.
    for path, nested in (
        ("$.journey[0].note", lambda c: c["journey"][0]),
        ("$.bridge_players[0].note", lambda c: c["bridge_players"][0]),
        ("$.provenance.note", lambda c: c["provenance"]),
    ):
        c = make_collection()
        nested(c)["note"] = "nested"
        assert f"private field {path!r} must never appear" in failures(c)
    c = make_collection()
    c["journey"][0]["note"] = "nested"
    assert "private field '$.journey[0].note' must never appear" in failures(c)


def test_empty_title_or_intro_refused() -> None:
    c = make_collection()
    c["intro"] = "  "
    c["title"] = ""
    text = failures(restamp(c))
    assert "intro is required" in text and "title is required" in text


# ---- major 3 and minor 8: text checks


def test_copy_must_not_suggest_a_private_collection_or_influence() -> None:
    c = make_collection()
    c["intro"] = "Straight from my collection."
    assert "forbidden phrase 'my collection'" in failures(restamp(c))
    c = make_collection()
    c["title"] = "Players who influenced a scene"
    assert "forbidden phrase 'influenced'" in failures(restamp(c))


def test_real_music_text_is_not_a_false_positive() -> None:
    graph = make_graph(
        names={
            10: "Local Natives",
            11: "Influenced By Nobody",
            12: "Home Of The Brave",
            13: "Far From My Home",
            14: "My Recordings",
        }
    )
    c = make_collection()
    c["title"] = "Far From My Home"
    c["intro"] = "Local heroes and my recordings of the scene, from home to stage."
    c["bridge_players"][0]["name"] = "Local Natives"
    c["bridge_players"][1]["name"] = "Influenced By Nobody"
    c["journey"][0]["via_names"] = ["Influenced By Nobody", "Home Of The Brave"]
    assert collection_failures(restamp(c), make_catalog(), graph) == []


def test_path_and_credential_text_is_refused_in_every_string() -> None:
    graph = make_graph(names={11: "Mr local/secrets"})
    c = make_collection()
    c["bridge_players"][1]["name"] = "Mr local/secrets"
    c["journey"][0]["via_names"] = ["Mr local/secrets", "Player 12"]
    assert "contains forbidden substring 'local/'" in failures(restamp(c), graph)
    c = make_collection()
    c["title"] = "see /home/someone/records"
    assert "$.title contains forbidden substring '/home/'" in failures(restamp(c))
    c = make_collection()
    c["records"][0] = "master-1 data/private"
    assert "forbidden substring 'data/private'" in failures(restamp(c))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/page",
        "https://",
        "https://user:pw@example.org/x",
        "https://www.discogs.com/user/someone/collection",
        "https://www.discogs.com/mywantlist",
        "https://www.discogs.com/wantlist?user=x",
        "https://example.org/page?token=abc",
        "https://example.org/page#frag",
        "https://example.org/a b",
    ],
)
def test_attribution_source_url_must_be_a_public_page(url: str) -> None:
    assert url_failures("u", url)
    c = make_collection()
    c["attribution"] = {"label": "A source", "source_url": url}
    assert "attribution.source_url" in failures(restamp(c))


def test_a_public_source_url_passes() -> None:
    assert url_failures("u", "https://www.discogs.com/master/12345-Some-Album") == []
    c = make_collection()
    c["attribution"] = {"label": "A source", "source_url": "https://example.org/essay"}
    assert collection_failures(restamp(c), make_catalog(), make_graph()) == []


@pytest.mark.parametrize(
    "value",
    ["tomorrow", "2026-01-01", "2026-01-01 00:00:00", "my notes", "2026-13-01T00:00:00Z", 5],
)
def test_generated_at_must_be_an_iso_timestamp(value: Any) -> None:
    c = make_collection()
    c["generated_at"] = value
    assert "generated_at must be an ISO-8601 timestamp" in failures(c)


def test_iso_timestamps_with_z_pass() -> None:
    c = make_collection()
    c["generated_at"] = "2026-11-17T12:30:00Z"
    assert collection_failures(c, make_catalog(), make_graph()) == []


def test_version_mismatch() -> None:
    c = make_collection()
    c["title"] = "Changed after stamping"
    assert "does not match recomputed content" in failures(c)


def test_generated_at_does_not_change_the_version() -> None:
    c = make_collection()
    c["generated_at"] = "2027-01-01T00:00:00+00:00"
    assert collection_failures(c, make_catalog(), make_graph()) == []


def test_stale_graph_version_in_lineage() -> None:
    graph = make_graph()
    graph["pathfinding_graph_version"] = "pathfinding-graph-v4-test-cccccccccccc"
    assert "built from pathfinding_graph version" in failures(make_collection(), graph)


def test_stale_catalog_version_in_lineage() -> None:
    catalog = make_catalog()
    catalog["catalog_version"] = "catalog-v1-test-dddddddddddd"
    text = failures(make_collection(), catalog=catalog)
    assert "built from catalog version" in text and "re-run promote-collection" in text


def test_graph_rebuild_that_removes_a_journey_edge_names_the_hop() -> None:
    edges = {k: v for k, v in PERFORMER_EDGES.items() if k != (11, 12)}
    graph = make_graph(edges)
    text = failures(make_collection(), graph)
    assert "journey hop 1 (master-1 -> master-3)" in text
    assert "no edge between performers 11 and 12" in text


def test_playable_pairs_validate_and_are_checked_against_the_graph() -> None:
    c = make_collection()
    c["playable_cohort"] = {
        "schema_version": 2,
        "route_policy": "shortest-first-found-v1",
        "pairs": [
            {
                "record_a": "master-1",
                "record_b": "master-3",
                "hop_count": 1,
                "via": [11, 12],
                "via_names": ["Player 11", "Player 12"],
                "evidence_release_ids": [1002],
            }
        ],
    }
    assert collection_failures(restamp(c), make_catalog(), make_graph()) == []
    c["playable_cohort"]["pairs"][0]["evidence_release_ids"] = [1]
    assert "playable pair 1" in failures(restamp(c))


# ---- major 4: the hop limit equals the site's search limit


def chain_fixture(performers: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """master-1 anchored at performer 20, master-2 at the chain's last performer;
    `performers` performers 20.. joined in a line; four other albums for the
    distinct-artist rule."""
    chain = list(range(20, 20 + performers))
    edges = {(a, b): 7000 + a for a, b in itertools.pairwise(chain)}
    anchors = {1: [chain[0]], 2: [chain[-1]], 3: [90, 91], 4: [91, 92]}
    graph = make_graph(edges, anchors)
    c = make_collection()
    c["records"] = ["master-1", "master-2", "master-3", "master-4"]
    c["bridge_players"] = [
        {"artist_id": 91, "name": "Player 91", "records": ["master-3", "master-4"]}
    ]
    c["journey"] = [
        {
            "from_record": "master-1",
            "to_record": "master-2",
            "via": chain,
            "via_names": [f"Player {n}" for n in chain],
            "evidence_release_ids": [7000 + a for a in chain[:-1]],
        }
    ]
    return restamp(c), make_catalog(4), graph


def test_hop_limit_matches_the_sites_search_budget() -> None:
    # The site's findAlbumRoute(maxHops=4) plus two stripped anchor hops: a route
    # through `via` has len(via) - 1 user hops, and 4 is the most it will search.
    assert MAX_SITE_HOPS == 4 and MAX_VIA == MAX_SITE_HOPS + 1
    at_limit, catalog, graph = chain_fixture(MAX_VIA)  # 4 hops
    assert collection_failures(at_limit, catalog, graph) == []
    over, catalog, graph = chain_fixture(MAX_VIA + 1)  # 5 hops
    text = failures(over, graph, catalog)
    assert "via must be 1..5 positive performer artist ids (at most 4 hops" in text


def test_a_single_shared_performer_is_zero_hops() -> None:
    c = make_collection()
    c["journey"] = [
        {
            "from_record": "master-3",
            "to_record": "master-4",
            "via": [13],
            "via_names": ["Player 13"],
            "evidence_release_ids": [],
        }
    ]
    assert collection_failures(restamp(c), make_catalog(), make_graph()) == []


# ---- minor 6: malformed input is reported, never raised


MALFORMED: list[Any] = [
    lambda c: c.update(collection_id=["x"]),
    lambda c: c.update(records="master-1"),
    lambda c: c.update(records=[["master-1"], "master-2", "master-3", "master-4"]),
    lambda c: c["journey"][0].update(from_record=["master-1"]),
    lambda c: c["journey"][0].update(to_record={"a": 1}),
    lambda c: c["journey"][0].update(via=[[1]]),
    lambda c: c.update(journey="nope"),
    lambda c: c.update(bridge_players=[{"artist_id": [1], "name": "x", "records": []}]),
    lambda c: c.update(
        bridge_players=[{"artist_id": 10, "name": "Player 10", "records": [["master-1"], 5]}]
    ),
    lambda c: c.update(
        playable_cohort={
            "schema_version": 2,
            "route_policy": "shortest-first-found-v1",
            "pairs": [
                {
                    "record_a": ["a"],
                    "record_b": {},
                    "hop_count": [],
                    "via": 1,
                    "via_names": 1,
                    "evidence_release_ids": 1,
                }
            ],
        }
    ),
    lambda c: c.update(attribution={"label": ["x"], "source_url": ["y"]}),
    lambda c: c.update(provenance={"inputs": [], "collection_version": []}),
    lambda c: c.update(provenance=[]),
    lambda c: c.update(title=["t"], intro={"i": 1}, generated_at=[1]),
    lambda c: c.update(schema_version=[1]),
]


@pytest.mark.parametrize("mutate", range(len(MALFORMED)))
def test_malformed_collections_are_failures_not_exceptions(mutate: int) -> None:
    c = make_collection()
    MALFORMED[mutate](c)
    assert collection_failures(c, make_catalog(), make_graph())


def test_malformed_catalog_graph_and_roots_are_failures_not_exceptions() -> None:
    c = make_collection()
    for catalog in (None, [], {"albums": 5}, {"albums": [1, None, {"id": []}]}):
        assert collection_failures(c, catalog, make_graph())
    for graph in (None, [], {"node_ids": "x"}, {"node_ids": [1], "names": [3]}):
        assert collection_failures(c, make_catalog(), graph)
    assert collection_failures([], make_catalog(), make_graph()) == ["collection must be an object"]
    assert collection_failures(None, make_catalog(), make_graph())


def test_malformed_index_entries_are_failures_not_exceptions() -> None:
    c = make_collection()
    for index in (
        {"schema_version": 1, "collections": [{"collection_id": ["x"]}]},
        {"schema_version": 1, "collections": [1, None]},
        {"schema_version": 1, "collections": "x"},
        [],
        {"schema_version": 1, "collections": [], "extra": 1},
    ):
        assert collections_failures(
            {"index": index, "files": {"a": c}}, make_catalog(), make_graph()
        )
    for group in ([], {"index": None}, {"index": None, "files": []}, "x"):
        assert collections_failures(group, make_catalog(), make_graph())


def entry_for(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "collection_id": c["collection_id"],
        "title": c["title"],
        "artifact_path": f"/data/collections/{c['collection_id']}.v1.json",
        "record_count": len(c["records"]),
        "collection_version": c["provenance"]["collection_version"],
    }


def test_group_passes_with_no_collections_and_checks_the_index() -> None:
    assert collections_failures(None, make_catalog(), make_graph()) == []
    c = make_collection()
    index = {"schema_version": 1, "collections": [entry_for(c)]}
    good = {"index": index, "files": {"synthetic-bridge": c}, "problems": []}
    assert collections_failures(good, make_catalog(), make_graph()) == []
    unlisted = {"index": index, "files": {"synthetic-bridge": c, "other": copy.deepcopy(c)}}
    assert "not listed in the collections index" in " ".join(
        collections_failures(unlisted, make_catalog(), make_graph())
    )
    assert "no file was loaded" in " ".join(
        collections_failures({"index": index, "files": {}}, make_catalog(), make_graph())
    )


# ---- major 2: every entry of collections/ is accounted for


def write_dir(root: Path, with_collection: bool = True) -> Path:
    directory = root / "collections"
    directory.mkdir()
    if with_collection:
        c = make_collection()
        (directory / "synthetic-bridge.v1.json").write_text(json.dumps(c))
        (directory / "index.v1.json").write_text(
            json.dumps({"schema_version": 1, "collections": [entry_for(c)]})
        )
    return directory


def dir_failures(root: Path) -> list[str]:
    loaded = load_collections_directory(root / "collections")
    return collections_failures(loaded, make_catalog(), make_graph())


def test_missing_and_empty_collections_directory_pass(tmp_path: Path) -> None:
    assert load_collections_directory(tmp_path / "collections") is None
    (tmp_path / "collections").mkdir()
    assert dir_failures(tmp_path) == []


def test_a_clean_collections_directory_passes(tmp_path: Path) -> None:
    write_dir(tmp_path)
    assert dir_failures(tmp_path) == []


@pytest.mark.parametrize(
    "name",
    [
        "collection-selection.private.json",
        "notes.json",
        "x.v2.json",
        "Upper.v1.json",
        "readme.txt",
        "synthetic-bridge.v1.json.bak",
    ],
)
def test_stray_files_in_collections_fail(tmp_path: Path, name: str) -> None:
    directory = write_dir(tmp_path)
    (directory / name).write_text('{"working_title": "secret"}')
    assert any(f"unexpected entry {name!r}" in f for f in dir_failures(tmp_path))


def test_a_subdirectory_or_symlink_in_collections_fails(tmp_path: Path) -> None:
    directory = write_dir(tmp_path)
    (directory / "sub").mkdir()
    (directory / "sub" / "a.v1.json").write_text("{}")
    (directory / "link.v1.json").symlink_to(directory / "synthetic-bridge.v1.json")
    text = " ".join(dir_failures(tmp_path))
    assert "unexpected entry 'sub'" in text and "unexpected entry 'link.v1.json'" in text


def test_malformed_json_in_collections_is_a_failure(tmp_path: Path) -> None:
    directory = write_dir(tmp_path)
    (directory / "synthetic-bridge.v1.json").write_text("{not json")
    text = " ".join(dir_failures(tmp_path))
    assert "synthetic-bridge.v1.json is unreadable or not valid JSON" in text
    (directory / "index.v1.json").write_bytes(b"\xff\xfe\x00")
    assert any("index.v1.json is unreadable" in f for f in dir_failures(tmp_path))


def test_collections_is_a_registered_group() -> None:
    from networked_players_contracts.artifact_lineage import ARTIFACT_CLASSES

    assert "collections" in PUBLIC_ARTIFACT_GROUPS
    assert ARTIFACT_CLASSES["collections"] == "live"
