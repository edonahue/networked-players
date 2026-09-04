"""CLI round-trip for `build-relationship-pool` (graph-expansion Phase 2's
"Pool B", plan section 21.3 slice X2). The pool query itself is unit-tested in
packages/graph-core/tests/test_relationship_pool.py; this pins the CLI wiring:
deriving catalog performers from the credit-membership artifact through the
ADR 0068 performer gate, the local-only output guard, and that the result feeds
`score-expansion-candidates` unchanged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import MASTER_SCHEMAS, SCHEMAS

SNAPSHOT_DATE = "20260601"


def _release(release_id: int, *, master_id: int) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": f"Release {release_id}",
        "country": None,
        "released": "1995",
        "master_id": master_id,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int,
    *,
    artist_id: int,
    name: str,
    credit_scope: str = "release_credit",
    role_text: str | None = "Guitar",
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
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


def _write_dataset(root: Path) -> Path:
    dataset_root = root / f"snapshot={SNAPSHOT_DATE}"
    (dataset_root / "table=releases").mkdir(parents=True)
    (dataset_root / "table=credits").mkdir(parents=True)
    (dataset_root / "table=tracks").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [_release(1, master_id=900), _release(2, master_id=901)],
            schema=SCHEMAS["releases"],
        ),
        dataset_root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                _credit(
                    1, artist_id=999, name="Billed", credit_scope="release_artist", role_text=None
                ),
                _credit(1, artist_id=100, name="Alice"),
                _credit(1, artist_id=200, name="Bob"),
                _credit(
                    2, artist_id=998, name="Other", credit_scope="release_artist", role_text=None
                ),
                # Only a non-performer credit shared with the catalog.
                _credit(2, artist_id=100, name="Alice", role_text="Design"),
            ],
            schema=SCHEMAS["credits"],
        ),
        dataset_root / "table=credits" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=SCHEMAS["tracks"]),
        dataset_root / "table=tracks" / "part-00000.parquet",
    )
    (dataset_root / "manifest.json").write_text(
        json.dumps({"snapshot_date": SNAPSHOT_DATE, "counts": {}})
    )
    return dataset_root


def _write_masters(root: Path) -> Path:
    masters_root = root / f"masters-snapshot={SNAPSHOT_DATE}"
    (masters_root / "table=masters").mkdir(parents=True)
    (masters_root / "table=master_artists").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "snapshot_date": SNAPSHOT_DATE,
                    "master_id": master_id,
                    "main_release_id": release_id,
                    "title": f"Master {master_id}",
                    "year": 1995,
                    "genres": ["Rock"],
                    "styles": [],
                    "data_quality": None,
                    "source_url": f"https://example.invalid/master/{master_id}",
                }
                for master_id, release_id in [(900, 1), (901, 2)]
            ],
            schema=MASTER_SCHEMAS["masters"],
        ),
        masters_root / "table=masters" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=MASTER_SCHEMAS["master_artists"]),
        masters_root / "table=master_artists" / "part-00000.parquet",
    )
    (masters_root / "manifest.json").write_text(
        json.dumps({"snapshot_date": SNAPSHOT_DATE, "counts": {"masters": 2}})
    )
    return masters_root


def _write_policy(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": SNAPSHOT_DATE,
                "allowed_release_ids": [1, 2],
                "allowed_release_count": 2,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
    return path


def _write_membership(path: Path) -> Path:
    """Deliberately inclusive, like the real artifact: Cara is a sleeve
    designer on a catalog album and must NOT count as a catalog performer."""
    path.write_text(
        json.dumps(
            {
                "albums": [
                    {
                        "album_id": "master-1",
                        "main_release_id": 1,
                        "credits": [
                            {
                                "artist_id": 100,
                                "credit_scope": "release_credit",
                                "role_text": "Bass",
                            },
                            {
                                "artist_id": 200,
                                "credit_scope": "release_credit",
                                "role_text": "Drums",
                            },
                            {
                                "artist_id": 300,
                                "credit_scope": "release_credit",
                                "role_text": "Design",
                            },
                        ],
                    }
                ]
            }
        )
    )
    return path


def _args(tmp_path: Path, output: Path, *extra: str) -> list[str]:
    return [
        "build-relationship-pool",
        "--onehop-root",
        str(_write_dataset(tmp_path)),
        "--masters-root",
        str(_write_masters(tmp_path)),
        "--album-credit-membership",
        str(_write_membership(tmp_path / "credit-membership.v1.json")),
        "--release-format-policy",
        str(_write_policy(tmp_path / "policy.json")),
        "--output",
        str(output),
        "--quiet",
        *extra,
    ]


def test_builds_a_pool_from_catalog_performers(tmp_path: Path) -> None:
    output = tmp_path / "local" / "analysis" / "expansion" / "round-1" / "pool.json"
    assert main(_args(tmp_path, output)) == 0

    pool = json.loads(output.read_text())
    # Master 900 shares Alice and Bob as real performers; 901 shares only a
    # Design credit, which the ADR 0068 gate rejects on both sides.
    assert [row["master_id"] for row in pool] == [900]
    assert pool[0]["catalog_performer_overlap"] == 2
    assert pool[0]["artist_id"] == 999


def test_non_performer_catalog_credits_do_not_become_catalog_performers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cara (300) is a sleeve designer on a catalog album. Using
    credit-membership raw would make her a "catalog performer" and drag her
    whole discography into the pool."""
    output = tmp_path / "local" / "pool.json"
    assert main(_args(tmp_path, output)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["catalog_performer_count"] == 2


def test_refuses_to_write_outside_local(tmp_path: Path) -> None:
    output = tmp_path / "apps" / "web" / "public" / "data" / "pool.json"
    with pytest.raises(ValueError, match="refuses to write outside local/"):
        main(_args(tmp_path, output))
    assert not output.exists()


def test_pool_output_feeds_score_expansion_candidates_unchanged(tmp_path: Path) -> None:
    """The whole point of matching rank-album-candidates' shape: the pool must
    substitute as --candidates with no transform step."""
    pool_path = tmp_path / "local" / "pool.json"
    assert main(_args(tmp_path, pool_path)) == 0

    graph = tmp_path / "graph.v4.json"
    graph.write_text(json.dumps({"node_ids": [100], "offsets": [0, 0], "neighbors": []}))
    scored = tmp_path / "local" / "scored.json"
    assert (
        main(
            [
                "score-expansion-candidates",
                "--onehop-root",
                str(tmp_path / f"snapshot={SNAPSHOT_DATE}"),
                "--masters-root",
                str(tmp_path / f"masters-snapshot={SNAPSHOT_DATE}"),
                "--candidates",
                str(pool_path),
                "--pathfinding-graph",
                str(graph),
                "--release-format-policy",
                str(tmp_path / "policy.json"),
                "--output",
                str(scored),
                "--quiet",
            ]
        )
        == 0
    )
    rows = json.loads(scored.read_text())["candidates"]
    assert [row["master_id"] for row in rows] == [900]
    assert rows[0]["eligibility"] == "eligible"
