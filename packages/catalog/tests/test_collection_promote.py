"""`promote-collection` (ADR 0074): synthetic fixtures only; nothing real."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.collection_promote import (
    CollectionPromotionError,
    build_collection,
    select_cluster,
)
from networked_players_catalog.review_packet import build_collection_data, input_hash
from networked_players_contracts.collection import collection_failures, collections_failures

CATALOG_VERSION = "catalog-v1-test-aaaaaaaaaaaa"
GRAPH_VERSION = "pathfinding-graph-v4-test-bbbbbbbbbbbb"
ANCHOR_PERFORMERS = {1: [10, 11], 2: [11, 12], 3: [12, 13], 4: [10, 13], 5: [13, 14]}
PERFORMER_EDGES = {(10, 11): 1001, (11, 12): 1002, (12, 13): 1003, (13, 14): 1004}
PRIVATE_NOTE = "remember to ask about the second pressing"
WORKING_TITLE = "Working Title Alpha"


def make_graph(edges: dict[tuple[int, int], int] | None = None) -> dict[str, Any]:
    edges = PERFORMER_EDGES if edges is None else edges
    node_ids = sorted([-n for n in ANCHOR_PERFORMERS] + [10, 11, 12, 13, 14])
    adjacency: dict[int, list[tuple[int, int]]] = {n: [] for n in node_ids}
    for album, performers in ANCHOR_PERFORMERS.items():
        for p in performers:
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
    return {
        "schema_version": 4,
        "pathfinding_graph_version": GRAPH_VERSION,
        "node_ids": node_ids,
        "names": [f"Anchor {-n}" if n < 0 else f"Player {n}" for n in node_ids],
        "offsets": offsets,
        "neighbors": neighbors,
        "evidence_release_ids": evidence,
        "album_virtual_nodes": [
            {"album_id": f"master-{n}", "virtual_artist_id": -n, "main_release_id": 500 + n}
            for n in ANCHOR_PERFORMERS
        ],
    }


def make_catalog() -> dict[str, Any]:
    return {
        "catalog_version": CATALOG_VERSION,
        "albums": [
            {"id": f"master-{n}", "artist_id": 100 + (n % 4), "artist": f"Artist {n % 4}"}
            for n in range(1, 6)
        ],
    }


def make_study() -> dict[str, Any]:
    albums = [
        {"id": f"master-{n}", "title": f"Album {n}", "artist": f"Artist {n % 4}", "year": 1970 + n}
        for n in range(1, 6)
    ]
    return {"qualifying_clusters": [{"albums": albums, "bridge_players": [], "artist_count": 4}]}


def make_selection(study: dict[str, Any], status: str = "keep") -> dict[str, Any]:
    kept = [{"id": f"master-{n}", "title": "x", "artist": "y", "year": 1} for n in (1, 2, 3, 4)]
    return {
        "private": True,
        "kind": "collection-selection",
        "warning": "PRIVATE",
        "input_hash": input_hash(build_collection_data(study)),
        "clusters": [
            {
                "cluster": 0,
                "status": status,
                "working_title": WORKING_TITLE,
                "note": PRIVATE_NOTE,
                "kept_records": kept,
            }
        ],
    }


def _build(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "records": ["master-1", "master-2", "master-3", "master-4"],
        "catalog": make_catalog(),
        "graph": make_graph(),
        "collection_id": "synthetic-bridge",
        "title": "Synthetic Bridge",
        "intro": "A made-up set of records for tests.",
        "generated_at": "2026-01-01T00:00:00+00:00",
    }
    kwargs.update(overrides)
    return build_collection(**kwargs)


def test_selection_round_trip_and_privacy(tmp_path: Path) -> None:
    study = make_study()
    selection = make_selection(study)
    chosen = select_cluster(selection, study, None)
    assert chosen["records"] == ["master-1", "master-2", "master-3", "master-4"]
    artifact = _build(records=chosen["records"])
    text = json.dumps(artifact)
    assert PRIVATE_NOTE not in text and WORKING_TITLE not in text
    assert collection_failures(artifact, make_catalog(), make_graph()) == []


def test_journey_over_synthetic_graph_has_expected_path_and_evidence() -> None:
    artifact = _build(journey=["master-1", "master-3", "master-4"])
    first, second = artifact["journey"]
    assert (first["via"], first["evidence_release_ids"]) == ([11, 12], [1002])
    assert first["via_names"] == ["Player 11", "Player 12"]
    # master-3 -> master-4 share performer 13: a single-performer route, no edges.
    assert (second["via"], second["evidence_release_ids"]) == ([13], [])


def test_playable_pairs_cover_reachable_pairs() -> None:
    pairs = _build()["playable_cohort"]["pairs"]
    assert len(pairs) == 6
    by = {(p["record_a"], p["record_b"]): p for p in pairs}
    assert by[("master-1", "master-4")]["via"] == [10]
    assert by[("master-1", "master-4")]["hop_count"] == 0
    assert by[("master-1", "master-3")]["hop_count"] == 1


def test_bridge_players_are_ranked_and_adjacent() -> None:
    names = [b["artist_id"] for b in _build()["bridge_players"]]
    assert names == [10, 11, 12, 13]


def test_output_is_deterministic() -> None:
    assert _build(journey=["master-1", "master-3"]) == _build(journey=["master-1", "master-3"])


def test_invalid_selection_is_refused_with_every_failure_named() -> None:
    with pytest.raises(CollectionPromotionError) as info:
        _build(records=["master-1", "master-2", "master-99"])
    message = str(info.value)
    assert "record 'master-99' is not in the catalog" in message
    assert "must hold 4..24 albums" in message


def test_journey_without_route_is_refused() -> None:
    graph = make_graph({})
    with pytest.raises(CollectionPromotionError, match="no route"):
        _build(graph=graph, journey=["master-1", "master-3"])


def test_selection_must_match_its_study_and_be_kept() -> None:
    study = make_study()
    selection = make_selection(study)
    other = make_study()
    other["qualifying_clusters"][0]["albums"].pop()
    with pytest.raises(CollectionPromotionError, match="not exported from this study"):
        select_cluster(selection, other, None)
    with pytest.raises(CollectionPromotionError, match="only 'keep'"):
        select_cluster(make_selection(study, status="needs-work"), study, 0)
    selection["clusters"][0]["kept_records"][0]["id"] = "master-77"
    with pytest.raises(CollectionPromotionError, match="not in the study"):
        select_cluster(selection, study, 0)


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    study = make_study()
    files = {
        "study": (tmp_path / "study.json", study),
        "selection": (tmp_path / "selection.json", make_selection(study)),
        "catalog": (tmp_path / "catalog.json", make_catalog()),
        "graph": (tmp_path / "graph.json", make_graph()),
    }
    for path, payload in files.values():
        path.write_text(json.dumps(payload))
    return {name: path for name, (path, _) in files.items()}


def _cli(tmp_path: Path, paths: dict[str, Path], *extra: str) -> int:
    return main(
        [
            "promote-collection",
            "--selection", str(paths["selection"]),
            "--study", str(paths["study"]),
            "--catalog", str(paths["catalog"]),
            "--graph", str(paths["graph"]),
            "--collection-id", "synthetic-bridge",
            "--title", "Synthetic Bridge",
            "--intro", "A made-up set of records for tests.",
            "--generated-at", "2026-01-01T00:00:00+00:00",
            "--journey", "master-1,master-3",
            *extra,
        ]
    )  # fmt: skip


def test_cli_stages_then_validates_as_a_group(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    staging = tmp_path / "local" / "staging"
    assert _cli(tmp_path, paths, "--output-dir", str(staging)) == 0
    index = json.loads((staging / "index.v1.json").read_text())
    artifact = json.loads((staging / "synthetic-bridge.v1.json").read_text())
    assert (
        collections_failures(
            {"index": index, "files": {"synthetic-bridge": artifact}}, make_catalog(), make_graph()
        )
        == []
    )
    first = (staging / "synthetic-bridge.v1.json").read_text()
    assert _cli(tmp_path, paths, "--output-dir", str(staging)) == 0
    assert (staging / "synthetic-bridge.v1.json").read_text() == first
    assert PRIVATE_NOTE not in first and WORKING_TITLE not in first


def test_cli_refuses_to_stage_under_public_and_publishes_only_explicitly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write_inputs(tmp_path)
    public = tmp_path / "apps" / "web" / "public" / "data"
    assert _cli(tmp_path, paths, "--output-dir", str(public / "collections")) == 1
    assert "refusing to stage under apps/web/public/" in capsys.readouterr().err
    assert not public.exists()
    assert _cli(tmp_path, paths, "--publish-to", str(public)) == 0
    assert (public / "collections" / "index.v1.json").is_file()


def test_cli_refuses_a_text_file_with_private_keys(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    text = tmp_path / "text.json"
    text.write_text(json.dumps({"title": "T", "intro": "I", "notes": "private"}))
    code = main(
        [
            "promote-collection", "--selection", str(paths["selection"]),
            "--study", str(paths["study"]), "--catalog", str(paths["catalog"]),
            "--graph", str(paths["graph"]), "--collection-id", "x-y",
            "--text-file", str(text), "--generated-at", "g",
            "--output-dir", str(tmp_path / "local" / "s"),
        ]
    )  # fmt: skip
    assert code == 1


def test_revalidation_after_graph_rebuild_that_drops_the_journey_edge() -> None:
    artifact = _build(journey=["master-1", "master-3"])
    rebuilt = make_graph({k: v for k, v in PERFORMER_EDGES.items() if k != (11, 12)})
    text = " | ".join(collection_failures(artifact, make_catalog(), rebuilt))
    assert "journey hop 1 (master-1 -> master-3)" in text
