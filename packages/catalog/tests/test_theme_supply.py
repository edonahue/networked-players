"""Theme-seed supply (Campaign Atlas SS) over a synthetic FULL corpus.

The synthetic world: a theme whose albums are ABSENT from the (tiny) one-hop corpus the
catalog was built from, so the only way to find them is to read the full corpus. Everything
here is invented; ids are not real Discogs ids.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import MASTER_SCHEMAS, SCHEMAS
from networked_players_catalog.review_packet import build_round_data

SNAPSHOT = "20260601"
REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_SPEC = REPO_ROOT / "data/fixtures/round-seed-spec/synthetic-round-seed-spec-v1.json"


def _release(rid: int, master_id: int | None) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT,
        "release_id": rid,
        "status": "Accepted",
        "title": f"Release {rid}",
        "country": None,
        "released": "1995",
        "master_id": master_id,
        "master_is_main_release": master_id is not None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{rid}",
    }


def _credit(
    rid: int, artist_id: int, name: str, *, scope: str = "release_artist", role: str | None = None
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT,
        "release_id": rid,
        "track_index": None,
        "track_path": None,
        "track_position": None,
        "track_title": None,
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _master(mid: int, rid: int, year: int, styles: list[str]) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT,
        "master_id": mid,
        "main_release_id": rid,
        "title": f"Master {mid}",
        "year": year,
        "genres": ["Rock"],
        "styles": styles,
        "data_quality": None,
        "source_url": f"https://example.invalid/master/{mid}",
    }


def _perf(rid: int, *people: tuple[int, str, str]) -> list[dict[str, Any]]:
    return [_credit(rid, a, n, scope="release_credit", role=r) for a, n, r in people]


P1, P2, P3 = (7001, "Pat", "Guitar"), (7002, "Quinn", "Bass"), (7003, "Rae", "Drums")
Q1, Q2 = (7101, "Sam", "Guitar"), (7102, "Tess", "Piano")
STONER = ["Stoner Rock"]

# release -> (master, year, styles, billed artist, performers)
WORLD: dict[int, tuple[int, int, list[str], tuple[int, str], list[tuple[int, str, str]]]] = {
    1: (9100, 1995, STONER, (9001, "Seed Band"), [P1, P2, P3]),  # theme 1 seed artist's master
    2: (9101, 2000, STONER, (9002, "Alpha"), [P1, P2]),  # overlap 2 -> in
    3: (9102, 2000, STONER, (9003, "Beta"), [P1]),  # overlap 1 -> out
    4: (9103, 2000, ["Pop Rock"], (9004, "Gamma"), [P1, P2]),  # wrong tag -> out
    5: (9104, 2015, STONER, (9005, "Delta"), [P1, P2]),  # outside decade bounds -> out
    7: (9106, 1998, STONER, (9006, "Epsilon"), [P1, P2]),  # no allowed release -> reasoned
    8: (9107, 1999, STONER, (9007, "Zeta"), [P1, (7002, "Quinn", "Producer")]),  # non-performer
    9: (9108, 1999, STONER, (9008, "Eta"), [P1, P2]),  # already published -> dropped
    20: (9500, 1980, ["Fusion"], (9500, "Fusion Seed"), [Q1, Q2]),  # theme 2 seed master
    21: (9501, 1985, ["Fusion"], (9501, "Fusion Next"), [Q1, Q2]),  # overlap 2, no tags -> in
}
ALLOWED = [1, 2, 3, 4, 5, 8, 9, 20, 21]  # release 7 is deliberately not format-allowed


def _write_world(root: Path) -> tuple[Path, Path]:
    full = root / f"full-snapshot={SNAPSHOT}"
    for table in ("releases", "credits", "tracks", "release_formats"):
        (full / f"table={table}").mkdir(parents=True)
    releases = [_release(rid, spec[0]) for rid, spec in WORLD.items()]
    credits: list[dict[str, Any]] = []
    for rid, (_m, _y, _s, billed, people) in WORLD.items():
        credits.append(_credit(rid, billed[0], billed[1]))
        credits += _perf(rid, *people)
    for table, rows in (
        ("releases", releases),
        ("credits", credits),
        ("tracks", []),
        ("release_formats", []),
    ):
        pq.write_table(
            pa.Table.from_pylist(rows, schema=SCHEMAS[table]),
            full / f"table={table}" / "part-00000.parquet",
        )
    (full / "manifest.json").write_text(
        json.dumps({"snapshot_date": SNAPSHOT, "schema_version": 3, "counts": {}})
    )
    masters = root / f"masters-snapshot={SNAPSHOT}"
    for table in ("masters", "master_artists"):
        (masters / f"table={table}").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [_master(m, rid, y, s) for rid, (m, y, s, _b, _p) in WORLD.items()],
            schema=MASTER_SCHEMAS["masters"],
        ),
        masters / "table=masters" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=MASTER_SCHEMAS["master_artists"]),
        masters / "table=master_artists" / "part-00000.parquet",
    )
    (masters / "manifest.json").write_text(json.dumps({"snapshot_date": SNAPSHOT, "counts": {}}))
    return full, masters


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    full, masters = _write_world(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": SNAPSHOT,
                "allowed_release_ids": ALLOWED,
                "allowed_release_count": len(ALLOWED),
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
                "snapshot_date": SNAPSHOT,
                "note": "synthetic",
                "exclusions": [],
            }
        )
    )
    catalog = tmp_path / "albums.v1.json"
    catalog.write_text(json.dumps({"albums": [{"master_id": 9108}]}))
    return {
        "full": full,
        "masters": masters,
        "policy": policy,
        "exclusions": exclusions,
        "catalog": catalog,
        "out": tmp_path / "local" / "round" / "theme-candidates.json",
    }


def _supply_argv(
    w: dict[str, Path], spec: Path = FIXTURE_SPEC, out: Path | None = None
) -> list[str]:
    return [
        "build-theme-candidates",
        "--seed-spec", str(spec),
        "--dataset", str(w["full"]),
        "--masters-root", str(w["masters"]),
        "--release-format-policy", str(w["policy"]),
        "--studio-album-exclusions", str(w["exclusions"]),
        "--already-published-catalog", str(w["catalog"]),
        "--output", str(out or w["out"]),
        "--quiet",
    ]  # fmt: skip


def _rows(path: Path) -> dict[int, dict[str, Any]]:
    return {r["master_id"]: r for r in json.loads(path.read_text())}


def test_theme_seed_outside_onehop_corpus_yields_eligible_candidates(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_supply_argv(world)) == 0
    summary = json.loads(capsys.readouterr().out)
    rows = _rows(world["out"])

    # In: theme 1 (seed artist's master + two-performer overlap in tag/decade), theme 2.
    for master_id in (9100, 9101, 9500, 9501):
        assert rows[master_id]["eligibility"] == "eligible", master_id
        assert rows[master_id]["main_release_id"] is not None
        assert rows[master_id]["artist_id"] is not None
    # Out: single shared performer, wrong tag, outside decade, non-performer role, published.
    for master_id in (9102, 9103, 9104, 9107, 9108):
        assert master_id not in rows, master_id
    # Present but reasoned, not silently dropped: nothing under the master is format-allowed.
    assert rows[9106]["eligibility"] == "no_format_allowed_release_under_master"
    assert rows[9106]["main_release_id"] is None

    by_theme = {t["theme"]: t for t in summary["themes"]}
    assert by_theme["synthetic desert theme"]["eligible_count"] == 2
    assert by_theme["synthetic fusion theme"]["eligible_count"] == 2
    assert summary["eligible_count"] == 4 and summary["candidate_count"] == 5

    why = {(e["theme"], e["source"]) for e in rows[9101]["themes"]}
    assert why == {("synthetic desert theme", "shared_performers")}
    assert rows[9101]["themes"][0]["shared_performers"] == 2
    assert {e["source"] for e in rows[9100]["themes"]} == {"seed_artist_master"}
    assert {e["source"] for e in rows[9500]["themes"]} == {"seed_master"}


def test_per_theme_cap_ranks_seed_masters_first(world: dict[str, Path], tmp_path: Path) -> None:
    spec = json.loads(FIXTURE_SPEC.read_text())
    spec["themes"][0]["candidate_cap"] = 1
    path = tmp_path / "capped.json"
    path.write_text(json.dumps(spec))
    assert main(_supply_argv(world, path)) == 0
    rows = _rows(world["out"])
    assert 9100 in rows and 9101 not in rows and 9106 not in rows


def test_candidates_flow_into_the_existing_scorer_and_review_packet(
    world: dict[str, Path], tmp_path: Path
) -> None:
    assert main(_supply_argv(world)) == 0
    # Credit evidence for the scorer lives in the FULL corpus: the one-hop corpus does not
    # have these albums, which is the point of this stage.
    graph = tmp_path / "graph.v4.json"
    graph.write_text(json.dumps({"node_ids": [7001], "offsets": [0, 0], "neighbors": []}))
    scored = tmp_path / "local" / "round" / "scored.json"
    code = main(
        [
            "score-expansion-candidates",
            "--onehop-root", str(world["full"]),
            "--masters-root", str(world["masters"]),
            "--candidates", str(world["out"]),
            "--pathfinding-graph", str(graph),
            "--release-format-policy", str(world["policy"]),
            "--output", str(scored),
            "--quiet",
        ]
    )  # fmt: skip
    assert code == 0
    payload = json.loads(scored.read_text())
    assert payload["eligible_count"] == 4
    by_master = {r["master_id"]: r for r in payload["candidates"]}
    assert by_master[9101]["eligibility"] == "eligible"
    assert by_master[9101]["roster_size"] >= 2
    assert by_master[9106]["eligibility"] != "eligible"
    data = build_round_data(payload, round_number=99)
    assert {a["master_id"] for a in data["rows"]} >= {9100, 9101, 9500, 9501}


def test_output_must_be_private_and_ignored(world: dict[str, Path], tmp_path: Path) -> None:
    assert main(_supply_argv(world, out=tmp_path / "public" / "candidates.json")) == 1
    assert not (tmp_path / "public").exists()
    # Inside a git work tree whose .gitignore does not cover it: refused.
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    exposed = repo / "local" / "x.json"
    assert main(_supply_argv(world, out=exposed)) == 1
    assert not exposed.exists()
    (repo / ".gitignore").write_text("local\n")
    assert main(_supply_argv(world, out=exposed)) == 0


def test_invalid_spec_is_refused_before_reading_the_corpus(
    world: dict[str, Path], tmp_path: Path
) -> None:
    spec = copy.deepcopy(json.loads(FIXTURE_SPEC.read_text()))
    del spec["themes"][0]["candidate_cap"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(spec))
    assert main(_supply_argv(world, path)) == 1
    assert not world["out"].exists()


def test_validate_round_seed_spec_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate-round-seed-spec", "--spec", str(FIXTURE_SPEC)]) == 0
    assert json.loads(capsys.readouterr().out)["lane_quotas"]["theme"] == 12
    broken = json.loads(FIXTURE_SPEC.read_text())
    broken["lane_shares_percent"]["theme"] = 10
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken))
    assert main(["validate-round-seed-spec", "--spec", str(path)]) == 1


# ------------------------------------------------------------------ re-widen seed


def _pool(path: Path, masters: list[int]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "note": "synthetic",
                "albums": [
                    {"master_id": m, "round": 2, "selection_source": "editorial"}
                    for m in sorted(masters)
                ],
            }
        )
    )
    return path


def _editorial(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "public-editorial-seed",
                "snapshot_date": SNAPSHOT,
                "generated_by": "synthetic",
                "generated_at": "2026-12-01T00:00:00+00:00",
                "note": "synthetic",
                "albums": [
                    {
                        "query_artist": None,
                        "query_title": None,
                        "master_id": 9100,
                        "main_release_id": 1,
                        "artist_id": 9001,
                        "artist": "Seed Band",
                        "title": "Master 9100",
                        "year": 1995,
                    }
                ],
            }
        )
    )
    return path


def _rewiden_argv(w: dict[str, Path], pool: Path, editorial: Path, out: Path) -> list[str]:
    return [
        "build-rewiden-seed",
        "--approved-pool", str(pool),
        "--editorial-seed", str(editorial),
        "--dataset", str(w["full"]),
        "--masters-root", str(w["masters"]),
        "--generated-at", "2026-12-01T00:00:00+00:00",
        "--output", str(out),
    ]  # fmt: skip


def test_rewiden_seed_carries_base_and_adds_only_approved(
    world: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "local" / "rewiden-seed.json"
    pool = _pool(tmp_path / "pool.json", [9100, 9101, 9501])
    assert main(_rewiden_argv(world, pool, _editorial(tmp_path / "ed.json"), out)) == 0
    payload = json.loads(out.read_text())
    from networked_players_graph_core.editorial_seed import (
        editorial_seed_failures,
        editorial_seed_release_ids,
    )

    assert editorial_seed_failures(payload) == []
    # Base entry kept (9100), approved-but-absent masters added, unapproved ones are not.
    assert editorial_seed_release_ids(payload) == [1, 2, 21]


def test_rewiden_seed_refuses_an_unseedable_approved_master(
    world: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "local" / "rewiden-seed.json"
    pool = _pool(tmp_path / "pool.json", [9100, 424242])
    assert main(_rewiden_argv(world, pool, _editorial(tmp_path / "ed.json"), out)) == 1
    assert not out.exists()
