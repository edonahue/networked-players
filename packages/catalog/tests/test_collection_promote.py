"""`promote-collection` (ADR 0074): synthetic fixtures only; nothing real."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.collection_promote import (
    CollectionPromotionError,
    _assert_no_private_text,
    _refuse_public_path,
    _require_public_data_root,
    build_collection,
    select_cluster,
    validate_approval,
)
from networked_players_catalog.review_packet import build_collection_data, input_hash
from networked_players_contracts.collection import collection_failures, collections_failures

CATALOG_VERSION = "catalog-v1-test-aaaaaaaaaaaa"
GRAPH_VERSION = "pathfinding-graph-v4-test-bbbbbbbbbbbb"
ANCHOR_PERFORMERS = {1: [10, 11], 2: [11, 12], 3: [12, 13], 4: [10, 13], 5: [13, 14]}
PERFORMER_EDGES = {(10, 11): 1001, (11, 12): 1002, (12, 13): 1003, (13, 14): 1004}
PRIVATE_NOTE = 'ask about the "second pressing" \\ before release'
WORKING_TITLE = "Working Title Alpha"
GENERATED_AT = "2026-01-01T00:00:00+00:00"
RECORDS = ["master-1", "master-2", "master-3", "master-4"]


def make_graph(
    edges: dict[tuple[int, int], int] | None = None,
    anchors: dict[int, list[int]] | None = None,
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
            for n in anchors
        ],
    }


def make_catalog(artists: dict[int, int] | None = None, albums: int = 5) -> dict[str, Any]:
    artists = artists or {}
    return {
        "catalog_version": CATALOG_VERSION,
        "albums": [
            {
                "id": f"master-{n}",
                "artist_id": artists.get(n, 100 + (n % 4)),
                "artist": f"Artist {n}",
            }
            for n in range(1, albums + 1)
        ],
    }


def make_study() -> dict[str, Any]:
    albums = [
        {"id": f"master-{n}", "title": f"Album {n}", "artist": f"Artist {n % 4}", "year": 1970 + n}
        for n in range(1, 6)
    ]
    return {"qualifying_clusters": [{"albums": albums, "bridge_players": [], "artist_count": 4}]}


def make_selection(study: dict[str, Any], status: str = "keep") -> dict[str, Any]:
    kept = [{"id": r, "title": "x", "artist": "y", "year": 1} for r in RECORDS]
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


def make_approval(study: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    approval: dict[str, Any] = {
        "schema_version": 1,
        "kind": "collection-approval",
        "private": True,
        "collection_id": "synthetic-bridge",
        "input_hash": input_hash(build_collection_data(study)),
        "cluster": 0,
        "records": list(RECORDS),
        "journey": ["master-1", "master-3"],
        "playable": True,
    }
    approval.update(overrides)
    return approval


def _build(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "records": list(RECORDS),
        "catalog": make_catalog(),
        "graph": make_graph(),
        "collection_id": "synthetic-bridge",
        "title": "Synthetic Bridge",
        "intro": "A made-up set of records for tests.",
        "generated_at": GENERATED_AT,
    }
    kwargs.update(overrides)
    return build_collection(**kwargs)


def test_selection_round_trip_and_privacy() -> None:
    study = make_study()
    chosen = select_cluster(
        make_selection(study),
        study,
        validate_approval(make_approval(study), collection_id="synthetic-bridge"),
    )
    assert chosen["records"] == RECORDS
    artifact = _build(records=chosen["records"])
    text = json.dumps(artifact)
    assert "second pressing" not in text and WORKING_TITLE not in text
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
    assert [b["artist_id"] for b in _build()["bridge_players"]] == [10, 11, 12, 13]


def test_output_is_deterministic() -> None:
    assert _build(journey=["master-1", "master-3"]) == _build(journey=["master-1", "master-3"])


# ---- major 1: same-artist records


def test_a_single_artists_own_records_are_not_a_bridge_nor_a_journey_nor_a_pair() -> None:
    # master-1 and master-4 share a primary artist; player 10 is on exactly those two.
    catalog = make_catalog({1: 7, 4: 7, 2: 8, 3: 9})
    artifact = _build(catalog=catalog)
    assert 10 not in [b["artist_id"] for b in artifact["bridge_players"]]
    pairs = {(p["record_a"], p["record_b"]) for p in artifact["playable_cohort"]["pairs"]}
    assert ("master-1", "master-4") not in pairs
    with pytest.raises(CollectionPromotionError, match="same primary artist"):
        _build(catalog=catalog, journey=["master-1", "master-4"])
    # a primary artist still bridges when their records span artists (11: m1 by 7, m2 by 8)
    assert 11 in [b["artist_id"] for b in artifact["bridge_players"]]


# ---- major 4: hop limit equals the site's


def chain(performers: int) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = list(range(20, 20 + performers))
    edges = {(a, b): 7000 + a for a, b in itertools.pairwise(nodes)}
    anchors = {1: [nodes[0]], 2: [nodes[-1]], 3: [90, 91], 4: [91, 92]}
    return make_graph(edges, anchors), make_catalog(albums=4)


def test_pair_at_the_site_hop_limit_is_published_and_one_over_is_not() -> None:
    graph, catalog = chain(5)  # 4 performer-to-performer hops: the site's maxHops
    artifact = _build(graph=graph, catalog=catalog, journey=["master-1", "master-2"])
    pair = next(
        p
        for p in artifact["playable_cohort"]["pairs"]
        if (p["record_a"], p["record_b"]) == ("master-1", "master-2")
    )
    assert pair["hop_count"] == 4 and len(pair["via"]) == 5
    assert artifact["journey"][0]["via"] == [20, 21, 22, 23, 24]
    graph, catalog = chain(6)  # 5 hops: beyond what the site searches
    over = _build(graph=graph, catalog=catalog)
    assert ("master-1", "master-2") not in {
        (p["record_a"], p["record_b"]) for p in over["playable_cohort"]["pairs"]
    }
    with pytest.raises(CollectionPromotionError, match="no route of at most 5 performers"):
        _build(graph=graph, catalog=catalog, journey=["master-1", "master-2"])


def test_invalid_selection_is_refused_with_every_failure_named() -> None:
    with pytest.raises(CollectionPromotionError) as info:
        _build(records=["master-1", "master-2", "master-99"])
    message = str(info.value)
    assert "record 'master-99' is not in the catalog" in message
    assert "must hold 4..24 albums" in message


def test_journey_without_route_is_refused() -> None:
    with pytest.raises(CollectionPromotionError, match="no route"):
        _build(graph=make_graph({}), journey=["master-1", "master-3"])


# ---- approval (item 9): the owner approves cluster, records, journey, playable


def test_approval_fixes_records_order_journey_and_playable() -> None:
    study = make_study()
    approval = make_approval(
        study,
        records=["master-3", "master-1", "master-2", "master-4"],
        journey=None,
        playable=False,
    )
    chosen = select_cluster(
        make_selection(study), study, validate_approval(approval, collection_id="synthetic-bridge")
    )
    assert chosen["records"] == ["master-3", "master-1", "master-2", "master-4"]
    assert chosen["journey"] is None and chosen["playable"] is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"records": RECORDS[:3]}, "exactly the selection's kept records"),
        ({"records": [*RECORDS[:3], "master-5"]}, "exactly the selection's kept records"),
        ({"records": [*RECORDS, "master-1"]}, "exactly the selection's kept records"),
        ({"input_hash": "0" * 16}, "approval was not written for this selection"),
        ({"cluster": 9}, "selection has no cluster 9"),
    ],
)
def test_approval_must_match_the_selection(overrides: dict[str, Any], message: str) -> None:
    study = make_study()
    approval = validate_approval(
        make_approval(study, **overrides), collection_id="synthetic-bridge"
    )
    with pytest.raises(CollectionPromotionError, match=message):
        select_cluster(make_selection(study), study, approval)


@pytest.mark.parametrize(
    "overrides",
    [
        {"collection_id": "other"},
        {"kind": "something"},
        {"private": False},
        {"cluster": "0"},
        {"records": "master-1"},
        {"journey": "master-1"},
        {"playable": "yes"},
        {"schema_version": 2},
    ],
)
def test_malformed_approval_is_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(CollectionPromotionError):
        validate_approval(
            make_approval(make_study(), **overrides), collection_id="synthetic-bridge"
        )
    with pytest.raises(CollectionPromotionError, match="exactly keys"):
        validate_approval({"kind": "collection-approval"}, collection_id="synthetic-bridge")


def test_selection_must_match_its_study_and_be_kept() -> None:
    study = make_study()
    approval = validate_approval(make_approval(study), collection_id="synthetic-bridge")
    selection = make_selection(study)
    other = make_study()
    other["qualifying_clusters"][0]["albums"].pop()
    with pytest.raises(CollectionPromotionError, match="not exported from this study"):
        select_cluster(selection, other, approval)
    with pytest.raises(CollectionPromotionError, match="only 'keep'"):
        select_cluster(make_selection(study, status="needs-work"), study, approval)
    selection["clusters"][0]["kept_records"][0]["id"] = "master-77"
    with pytest.raises(CollectionPromotionError, match="not in the study"):
        select_cluster(selection, study, approval)


# ---- minor 7: the private-text backstop


def test_private_text_guard_matches_decoded_values_not_json_escapes() -> None:
    artifact = _build(intro=f"Notes: {PRIVATE_NOTE}")
    with pytest.raises(CollectionPromotionError, match="note text appears"):
        _assert_no_private_text(
            artifact, working_title=WORKING_TITLE, note=PRIVATE_NOTE, title="Synthetic Bridge"
        )


def test_private_text_guard_catches_a_sentence_of_the_note() -> None:
    artifact = _build(intro="We will ask about the second pressing soon.")
    with pytest.raises(CollectionPromotionError, match="note text appears"):
        _assert_no_private_text(
            artifact,
            working_title="",
            note="Ask about the second pressing. Also unrelated stuff.",
            title="Synthetic Bridge",
        )


def test_short_or_common_private_text_does_not_refuse_legitimate_copy() -> None:
    artifact = _build(intro="A set of jazz records for tests.")
    _assert_no_private_text(artifact, working_title="Jazz", note="jazz", title="Synthetic Bridge")


def test_a_working_title_is_public_only_as_the_title() -> None:
    artifact = _build(title=WORKING_TITLE)
    _assert_no_private_text(
        artifact, working_title=WORKING_TITLE, note="", title=WORKING_TITLE
    )  # explicit title: allowed
    leaked = _build(intro=f"This is {WORKING_TITLE.lower()} for the record.")
    with pytest.raises(CollectionPromotionError, match="working title text appears"):
        _assert_no_private_text(
            leaked, working_title=WORKING_TITLE, note="", title="Synthetic Bridge"
        )


# ---- CLI


def _write_inputs(tmp_path: Path, **approval_overrides: Any) -> dict[str, Path]:
    study = make_study()
    files = {
        "study": (tmp_path / "study.json", study),
        "selection": (tmp_path / "selection.json", make_selection(study)),
        "approval": (tmp_path / "approval.json", make_approval(study, **approval_overrides)),
        "catalog": (tmp_path / "catalog.json", make_catalog()),
        "graph": (tmp_path / "graph.json", make_graph()),
    }
    for path, payload in files.values():
        path.write_text(json.dumps(payload))
    return {name: path for name, (path, _) in files.items()}


def _cli(paths: dict[str, Path], *extra: str, generated_at: str = GENERATED_AT) -> int:
    return main(
        [
            "promote-collection",
            "--selection", str(paths["selection"]),
            "--study", str(paths["study"]),
            "--approval", str(paths["approval"]),
            "--catalog", str(paths["catalog"]),
            "--graph", str(paths["graph"]),
            "--collection-id", "synthetic-bridge",
            "--title", "Synthetic Bridge",
            "--intro", "A made-up set of records for tests.",
            "--generated-at", generated_at,
            *extra,
        ]
    )  # fmt: skip


def test_cli_stages_then_validates_as_a_group(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    staging = tmp_path / "local" / "staging"
    assert _cli(paths, "--output-dir", str(staging)) == 0
    index = json.loads((staging / "index.v1.json").read_text())
    artifact = json.loads((staging / "synthetic-bridge.v1.json").read_text())
    assert not collections_failures(
        {"index": index, "files": {"synthetic-bridge": artifact}}, make_catalog(), make_graph()
    )
    assert len(artifact["journey"]) == 1
    first = (staging / "synthetic-bridge.v1.json").read_text()
    assert _cli(paths, "--output-dir", str(staging)) == 0
    assert (staging / "synthetic-bridge.v1.json").read_text() == first
    assert "second pressing" not in first and WORKING_TITLE not in first


def make_data_root(tmp_path: Path) -> Path:
    data = tmp_path / "apps" / "web" / "public" / "data"
    (data / "catalog").mkdir(parents=True)
    (data / "catalog" / "albums.v1.json").write_text("{}")
    return data


def test_cli_refuses_to_stage_under_public_and_publishes_only_to_the_data_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write_inputs(tmp_path)
    data = make_data_root(tmp_path)
    assert _cli(paths, "--output-dir", str(data / "collections")) == 1
    assert "refusing to stage under apps/web/public/" in capsys.readouterr().err
    assert not (data / "collections").exists()
    # a missing /data, or any other directory, is refused
    for bad in (data.parent, tmp_path / "elsewhere", data / "catalog"):
        assert _cli(paths, "--publish-to", str(bad)) == 1
        assert "--publish-to must be the public data root" in capsys.readouterr().err
    assert not (data.parent / "collections").exists()
    assert _cli(paths, "--publish-to", str(data)) == 0
    assert (data / "collections" / "index.v1.json").is_file()


def test_public_path_guard_resolves_symlinks_and_dotdot(tmp_path: Path) -> None:
    data = make_data_root(tmp_path)
    link = tmp_path / "innocent"
    link.symlink_to(data)
    sneaky = tmp_path / "local" / ".." / "apps" / "web" / "public" / "data" / "collections"
    for path in (link / "collections", sneaky, data):
        with pytest.raises(CollectionPromotionError, match="refusing to stage"):
            _refuse_public_path(path)
    _refuse_public_path(tmp_path / "local" / "staging")  # fine
    with pytest.raises(CollectionPromotionError):
        _require_public_data_root(link / "catalog")
    assert _require_public_data_root(link) == data.resolve()


def test_cli_refuses_a_text_file_with_nested_private_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write_inputs(tmp_path)
    text = tmp_path / "text.json"
    # Only the private-field denylist rejects this (the key set check allows `attribution`).
    text.write_text(
        json.dumps(
            {
                "title": "T",
                "intro": "I",
                "attribution": {"label": "L", "source_url": "https://x.org/a", "reviewed_by": "me"},
            }
        )
    )
    code = main(
        [
            "promote-collection", "--selection", str(paths["selection"]),
            "--study", str(paths["study"]), "--approval", str(paths["approval"]),
            "--catalog", str(paths["catalog"]), "--graph", str(paths["graph"]),
            "--collection-id", "synthetic-bridge", "--text-file", str(text),
            "--generated-at", GENERATED_AT, "--output-dir", str(tmp_path / "local" / "s"),
        ]
    )  # fmt: skip
    assert code == 1
    err = capsys.readouterr().err
    assert "private field '$.attribution.reviewed_by' must never appear" in err


def test_cli_refuses_a_bad_generated_at_and_a_dirty_staging_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write_inputs(tmp_path)
    staging = tmp_path / "local" / "staging"
    assert _cli(paths, "--output-dir", str(staging), generated_at="my private notes") == 1
    assert "--generated-at must be an ISO-8601 timestamp" in capsys.readouterr().err
    staging.mkdir(parents=True)
    (staging / "collection-selection.private.json").write_text("{}")
    assert _cli(paths, "--output-dir", str(staging)) == 1
    assert "unexpected entry 'collection-selection.private.json'" in capsys.readouterr().err


def test_cli_requires_a_valid_approval(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = _write_inputs(tmp_path, records=RECORDS[:3])
    assert _cli(paths, "--output-dir", str(tmp_path / "local" / "s")) == 1
    assert "exactly the selection's kept records" in capsys.readouterr().err


def test_revalidation_after_graph_rebuild_that_drops_the_journey_edge() -> None:
    artifact = _build(journey=["master-1", "master-3"])
    rebuilt = make_graph({k: v for k, v in PERFORMER_EDGES.items() if k != (11, 12)})
    text = " | ".join(collection_failures(artifact, make_catalog(), rebuilt))
    assert "journey hop 1 (master-1 -> master-3)" in text
