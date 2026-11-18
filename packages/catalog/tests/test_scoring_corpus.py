"""`build-scoring-corpus` (Round 2, R2-2): the bounded corpus must be
sufficient for `score-expansion-candidates` -- scoring against it is
byte-identical to scoring against the full corpus -- while staying bounded
(releases of non-candidate masters that are not in the one-hop corpus are
absent), atomic, and local-only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import MASTER_SCHEMAS, SCHEMA_VERSION, SCHEMAS
from networked_players_catalog.discogs.scoring_corpus import ScoringCorpusError

SNAPSHOT_DATE = "20260601"


def _release(release_id: int, *, master_id: int | None, released: str = "1995") -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Release {release_id}",
        "country": None,
        "released": released,
        "master_id": master_id,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(release_id: int, artist_id: int, name: str, role: str | None = None) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": "release_artist",
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _track(release_id: int) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": 0,
        "parent_track_index": None,
        "track_path": "0",
        "position": "1",
        "title": f"Track of {release_id}",
        "duration": None,
    }


def _format(release_id: int) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "format_index": 0,
        "format_name": "CD",
        "quantity": 1,
        "format_text": None,
        "descriptions": ["Album"],
    }


def _write_corpus(
    root: Path,
    *,
    releases: list[dict[str, Any]],
    credits: list[dict[str, Any]],
    extra_manifest: dict[str, Any] | None = None,
) -> Path:
    dataset = root / f"snapshot={SNAPSHOT_DATE}"
    rows = {
        "releases": releases,
        "credits": credits,
        "tracks": [_track(r["release_id"]) for r in releases],
        "release_formats": [_format(r["release_id"]) for r in releases],
    }
    for table, table_rows in rows.items():
        (dataset / f"table={table}").mkdir(parents=True)
        pq.write_table(
            pa.Table.from_pylist(table_rows, schema=SCHEMAS[table]),
            dataset / f"table={table}" / "part-00000.parquet",
        )
    (dataset / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_date": SNAPSHOT_DATE,
                "schema_version": SCHEMA_VERSION,
                "source_url": "https://example.invalid/dump",
                **(extra_manifest or {}),
            }
        )
    )
    return dataset


def _write_masters(root: Path) -> Path:
    masters = root / f"masters-snapshot={SNAPSHOT_DATE}"
    (masters / "table=masters").mkdir(parents=True)
    (masters / "table=master_artists").mkdir(parents=True)
    rows = [
        # (master_id, main_release_id)
        (900, 1),  # main release 1 is in the one-hop corpus; reissue 5 only in full
        (901, 2),
        (902, 3),  # whole master only in the full corpus
        (903, 9),  # main release 9's releases row carries master_id NULL
        (904, 4),  # NOT a candidate
    ]
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "snapshot_date": SNAPSHOT_DATE,
                    "master_id": master_id,
                    "main_release_id": main_release_id,
                    "title": f"Master {master_id}",
                    "year": 1995,
                    "genres": ["Rock"],
                    "styles": ["Indie Rock"],
                    "data_quality": None,
                    "source_url": f"https://example.invalid/master/{master_id}",
                }
                for master_id, main_release_id in rows
            ],
            schema=MASTER_SCHEMAS["masters"],
        ),
        masters / "table=masters" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=MASTER_SCHEMAS["master_artists"]),
        masters / "table=master_artists" / "part-00000.parquet",
    )
    (masters / "manifest.json").write_text(json.dumps({"snapshot_date": SNAPSHOT_DATE}))
    return masters


FULL_RELEASES = [
    _release(1, master_id=900, released="1995"),
    _release(5, master_id=900, released="1994"),  # earlier reissue, full-only
    _release(2, master_id=901),
    _release(3, master_id=902),
    _release(9, master_id=None),
    _release(4, master_id=904),  # non-candidate, full-only
    _release(7, master_id=None),  # one-hop-only noise (not a candidate release)
    _release(8, master_id=None),  # full-only noise
]
FULL_CREDITS = [
    _credit(1, 100, "Alice"),
    _credit(1, 200, "Bob"),
    _credit(5, 100, "Alice"),
    _credit(5, 300, "Cara"),
    _credit(5, 301, "Cara Producer", role="Producer"),
    _credit(2, 400, "Dan"),
    _credit(3, 500, "Eve"),
    _credit(3, 501, "Fay", role="Guitar"),
    _credit(9, 600, "Gus"),
    _credit(4, 700, "Hal"),
    _credit(7, 100, "Alice"),
    _credit(8, 800, "Ivy"),
]
ONEHOP_RELEASE_IDS = {1, 2, 7}


def _fixtures(tmp_path: Path) -> dict[str, Path]:
    full = _write_corpus(tmp_path / "full", releases=FULL_RELEASES, credits=FULL_CREDITS)
    onehop = _write_corpus(
        tmp_path / "onehop",
        releases=[r for r in FULL_RELEASES if r["release_id"] in ONEHOP_RELEASE_IDS],
        credits=[c for c in FULL_CREDITS if c["release_id"] in ONEHOP_RELEASE_IDS],
    )
    masters = _write_masters(tmp_path)
    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps(
            [{"master_id": m, "artist_id": 100, "artist_name": "A"} for m in (900, 901, 902, 903)]
        )
    )
    policy = tmp_path / "policy.json"
    # Release 1 is NOT format-allowed, so master 900 falls back to the
    # earliest allowed release (5, which exists only in the full corpus).
    policy.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": SNAPSHOT_DATE,
                "allowed_release_ids": [5, 2, 3, 9],
                "allowed_release_count": 4,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
    exclusions = tmp_path / "exclusions.json"
    exclusions.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": "studio-album-v1",
                "snapshot_date": SNAPSHOT_DATE,
                "note": "test fixture",
                "exclusions": [{"master_id": 901}],
            }
        )
    )
    graph = tmp_path / "graph.v4.json"
    graph.write_text(
        json.dumps({"node_ids": [100, 500, -1], "offsets": [0, 1, 1, 1], "neighbors": [2]})
    )
    return {
        "full": full,
        "onehop": onehop,
        "masters": masters,
        "candidates": candidates,
        "policy": policy,
        "exclusions": exclusions,
        "graph": graph,
    }


def _build(tmp_path: Path, f: dict[str, Path], output_root: Path) -> int:
    return main(
        [
            "build-scoring-corpus",
            "--onehop-root",
            str(f["onehop"]),
            "--full-root",
            str(f["full"]),
            "--masters-root",
            str(f["masters"]),
            "--candidates",
            str(f["candidates"]),
            "--output-root",
            str(output_root),
            "--quiet",
        ]
    )


def _score(f: dict[str, Path], corpus: Path, output: Path) -> bytes:
    exit_code = main(
        [
            "score-expansion-candidates",
            "--onehop-root",
            str(corpus),
            "--masters-root",
            str(f["masters"]),
            "--candidates",
            str(f["candidates"]),
            "--pathfinding-graph",
            str(f["graph"]),
            "--release-format-policy",
            str(f["policy"]),
            "--studio-album-exclusions",
            str(f["exclusions"]),
            "--output",
            str(output),
            "--quiet",
        ]
    )
    assert exit_code == 0
    return output.read_bytes()


def _release_ids(dataset: Path, table: str = "releases") -> set[int]:
    glob = str(dataset / f"table={table}" / "*.parquet")
    rows = duckdb.connect().execute(f"SELECT release_id FROM read_parquet('{glob}')").fetchall()
    return {int(r[0]) for r in rows}


def test_scoring_against_bounded_corpus_is_byte_identical_to_full(tmp_path: Path) -> None:
    f = _fixtures(tmp_path)
    output_root = tmp_path / "local" / "scoring-corpus"
    assert _build(tmp_path, f, output_root) == 0
    bounded = output_root / f"snapshot={SNAPSHOT_DATE}"

    scores = tmp_path / "local" / "scores"
    scores.mkdir(parents=True)
    on_full = _score(f, f["full"], scores / "full.json")
    on_bounded = _score(f, bounded, scores / "bounded.json")
    assert on_bounded == on_full

    rows = {r["master_id"]: r for r in json.loads(on_bounded)["candidates"]}
    # Exercises the cases the corpus must cover: fallback to a full-only
    # reissue (900), exclusion (901), full-only master (902), and a main
    # release whose releases row has no master_id (903: main release 9 has no
    # master_id, so it is ineligible, identically in both corpora).
    assert rows[900]["main_release_id"] == 5
    assert rows[900]["roster_artist_ids"] == [100, 300, 301]
    assert rows[901]["eligibility"] == "curated_master_exclusion"
    assert rows[902]["roster_artist_ids"] == [500, 501]
    assert rows[900]["bridge_span"] == 1 and rows[902]["bridge_span"] == 0


def test_bounded_corpus_contents_and_manifest(tmp_path: Path) -> None:
    f = _fixtures(tmp_path)
    output_root = tmp_path / "local" / "scoring-corpus"
    assert _build(tmp_path, f, output_root) == 0
    bounded = output_root / f"snapshot={SNAPSHOT_DATE}"

    # one-hop {1,2,7} + candidate releases {1,5,2,3,9}; NOT the non-candidate 4 or 8.
    for table in ("releases", "tracks", "credits", "release_formats"):
        assert _release_ids(bounded, table) == {1, 2, 3, 5, 7, 9}
    # No duplicated release rows even though 1 and 2 are in both sources.
    glob = str(bounded / "table=releases" / "*.parquet")
    assert duckdb.connect().execute(f"SELECT count(*) FROM read_parquet('{glob}')").fetchone() == (
        6,
    )

    manifest = json.loads((bounded / "manifest.json").read_text())
    expansion = manifest["expansion"]
    assert expansion["kind"] == "scoring-corpus"
    for key, path in (
        ("onehop_manifest_sha256", f["onehop"]),
        ("full_corpus_manifest_sha256", f["full"]),
        ("masters_manifest_sha256", f["masters"]),
    ):
        import hashlib

        assert expansion[key] == hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()
    assert (
        expansion["candidates_sha256"] == hashlib.sha256(f["candidates"].read_bytes()).hexdigest()
    )
    assert expansion["candidate_release_count"] == 5
    assert expansion["extra_release_count"] == 3  # 5, 3, 9
    assert manifest["counts"]["releases"] == 6
    # No staging directory is left behind.
    assert [p.name for p in output_root.iterdir()] == [f"snapshot={SNAPSHOT_DATE}"]


def test_refuses_output_outside_local(tmp_path: Path) -> None:
    f = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="refuses to write outside local/"):
        _build(tmp_path, f, tmp_path / "public" / "out")


def test_refuses_existing_output_without_overwrite(tmp_path: Path) -> None:
    f = _fixtures(tmp_path)
    output_root = tmp_path / "local" / "scoring-corpus"
    assert _build(tmp_path, f, output_root) == 0
    with pytest.raises(FileExistsError):
        _build(tmp_path, f, output_root)


def test_refuses_mismatched_snapshot_and_leaves_nothing(tmp_path: Path) -> None:
    f = _fixtures(tmp_path)
    (f["masters"] / "manifest.json").write_text(json.dumps({"snapshot_date": "20250101"}))
    output_root = tmp_path / "local" / "scoring-corpus"
    with pytest.raises(ScoringCorpusError, match="mismatched snapshots"):
        _build(tmp_path, f, output_root)
    assert not output_root.exists() or not list(output_root.iterdir())


def test_scorer_output_is_identical_with_and_without_credit_edges(tmp_path: Path) -> None:
    """The scorer opens the corpus with build_edges=False; the in-process
    result must equal the one from a graph with edges built."""
    from networked_players_graph_core.graph import CreditGraph
    from networked_players_graph_core.score_expansion_candidates import (
        score_expansion_candidates,
    )

    f = _fixtures(tmp_path)
    candidates = json.loads(f["candidates"].read_text())
    policy = frozenset(json.loads(f["policy"].read_text())["allowed_release_ids"])
    pathfinding_graph = json.loads(f["graph"].read_text())
    outputs = []
    for build_edges in (True, False):
        with CreditGraph.open(f["full"], build_edges=build_edges) as graph:
            graph.attach_masters(f["masters"])
            outputs.append(
                json.dumps(
                    score_expansion_candidates(
                        graph,
                        candidates,
                        existing_node_ids=frozenset({100, 500}),
                        allowed_release_ids=policy,
                        master_exclusions=frozenset({901}),
                        pathfinding_graph=pathfinding_graph,
                        quiet=True,
                    ),
                    sort_keys=True,
                )
            )
    assert outputs[0] == outputs[1]


def test_refuses_onehop_with_wrong_schema_version(tmp_path: Path) -> None:
    f = _fixtures(tmp_path)
    manifest_path = f["onehop"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = SCHEMA_VERSION + 1
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ScoringCorpusError, match="one-hop corpus schema_version"):
        _build(tmp_path, f, tmp_path / "local" / "out")


def test_refuses_onehop_derived_from_a_different_full_corpus(tmp_path: Path) -> None:
    f = _fixtures(tmp_path)
    manifest_path = f["onehop"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["expansion"] = {"source_manifest_sha256": "0" * 64}
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ScoringCorpusError, match="source_manifest_sha256"):
        _build(tmp_path, f, tmp_path / "local" / "out")


def test_accepts_onehop_recording_the_matching_source_sha(tmp_path: Path) -> None:
    import hashlib

    f = _fixtures(tmp_path)
    manifest_path = f["onehop"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256((f["full"] / "manifest.json").read_bytes()).hexdigest()
    manifest["expansion"] = {"source_manifest_sha256": digest}
    manifest_path.write_text(json.dumps(manifest))
    assert _build(tmp_path, f, tmp_path / "local" / "out") == 0


def test_self_check_catches_track_and_format_count_drift(tmp_path: Path) -> None:
    """A one-hop corpus missing a track/format row of a release it already
    holds is detected against the full corpus (credits were already checked)."""
    f = _fixtures(tmp_path)
    for table in ("tracks", "release_formats"):
        path = f["onehop"] / f"table={table}" / "part-00000.parquet"
        table_rows = pq.read_table(path)
        pq.write_table(table_rows.slice(1), path)  # drop one row
    with pytest.raises(ScoringCorpusError, match="count_mismatch_vs_full"):
        _build(tmp_path, f, tmp_path / "local" / "out")
