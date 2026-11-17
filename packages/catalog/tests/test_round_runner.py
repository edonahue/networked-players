"""The round runner (ADR 0072 section 3) over a tiny synthetic corpus.

Everything here is synthetic. The synthetic end-to-end exercises every stage
except two that are pluggable by design: the album-art stage (needs the Discogs
API and a private cache; tests inject a synthetic registry) and Prettier
(tests inject a recording formatter). The default formatter is covered only by
its failure path, and the ignore-file filter against the real
apps/web/.prettierignore.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog import round_runner as rr
from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import MASTER_SCHEMAS, SCHEMAS
from networked_players_contracts.album_art import album_art_version
from networked_players_graph_core.lineage_inputs import lineage_inputs, stamp_inputs

SNAPSHOT = "20260601"
GENERATED_AT = "2026-12-01T00:00:00+00:00"
TODAY = "2026-12-01"
MERGE = "2026-12-05"
# cutover = merge + 3 days = 2026-12-08; the previous manifest covers 12-06 and 12-07.

ALBUMS = {  # release id -> (title, artist id, artist name)
    1: ("First Light", 100, "Alice"),
    2: ("Second Wind", 300, "Cara"),
    3: ("Third Wave", 400, "Dana"),
    4: ("Fourth Dream", 500, "Eve"),
}
PERFORMERS = {1: "Guitar", 2: "Bass", 3: "Drums", 4: "Piano"}  # Bob (200) plays on all


def _release(rid: int) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT,
        "release_id": rid,
        "status": "Accepted",
        "title": ALBUMS[rid][0],
        "country": None,
        "released": "1995",
        "master_id": 900 + rid,
        "master_is_main_release": True,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{rid}",
    }


def _credit(rid: int, aid: int, name: str, scope: str, role: str | None) -> dict[str, Any]:
    track = scope == "track_artist"
    return {
        "snapshot_date": SNAPSHOT,
        "release_id": rid,
        "track_index": 0 if track else None,
        "track_path": "0" if track else None,
        "track_position": "1" if track else None,
        "track_title": "Track 1" if track else None,
        "credit_scope": scope,
        "artist_id": aid,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role,
        "credited_tracks_text": None,
        "is_linked": True,
        "playable_identity": True,
    }


def _write_corpus(root: Path) -> tuple[Path, Path]:
    onehop = root / "onehop"
    (onehop / "table=releases").mkdir(parents=True)
    (onehop / "table=credits").mkdir()
    (onehop / "table=tracks").mkdir()
    credits: list[dict[str, Any]] = []
    for rid, (_, aid, name) in ALBUMS.items():
        credits += [
            _credit(rid, aid, name, "release_artist", None),
            _credit(rid, aid, name, "track_artist", PERFORMERS[rid]),
            _credit(rid, 200, "Bob", "release_artist", None),
            _credit(rid, 200, "Bob", "track_artist", "Guitar"),
        ]
    for table, rows in (
        ("releases", [_release(r) for r in ALBUMS]),
        ("credits", credits),
        ("tracks", []),
    ):
        pq.write_table(
            pa.Table.from_pylist(rows, schema=SCHEMAS[table]),
            onehop / f"table={table}" / "part-00000.parquet",
        )
    (onehop / "manifest.json").write_text(json.dumps({"snapshot_date": SNAPSHOT, "counts": {}}))

    masters = root / "masters"
    (masters / "table=masters").mkdir(parents=True)
    (masters / "table=master_artists").mkdir()
    rows = [
        {
            "snapshot_date": SNAPSHOT,
            "master_id": 900 + rid,
            "main_release_id": rid,
            "title": ALBUMS[rid][0],
            "year": 1995,
            "genres": [],
            "styles": [],
            "data_quality": None,
            "source_url": f"https://example.invalid/master/{900 + rid}",
        }
        for rid in ALBUMS
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=MASTER_SCHEMAS["masters"]),
        masters / "table=masters" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=MASTER_SCHEMAS["master_artists"]),
        masters / "table=master_artists" / "part-00000.parquet",
    )
    (masters / "manifest.json").write_text(
        json.dumps({"snapshot_date": SNAPSHOT, "counts": {"masters": 4}})
    )
    return onehop, masters


def _pool(path: Path, masters: list[int], new_round: int | None = None) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "note": "synthetic",
                "albums": [
                    {
                        "master_id": m,
                        "round": 2 if (new_round and m == 904) else 0,
                        "selection_source": "editorial",
                    }
                    for m in masters
                ],
            }
        )
    )
    return path


def _editorial(path: Path, rids: list[int]) -> Path:
    path.write_text(
        json.dumps({"albums": [{"artist": ALBUMS[r][2], "title": ALBUMS[r][0]} for r in rids]})
    )
    return path


def _synthetic_art(ctx: rr.Ctx) -> None:
    catalog = json.loads(ctx.o(rr.CATALOG).read_text())
    entries = [
        {
            "album_id": a["id"],
            "main_release_id": a["main_release_id"],
            "uri150": f"https://i.discogs.com/{a['id']}/150.jpg",
            "uri": f"https://i.discogs.com/{a['id']}/full.jpg",
            "width": 600,
            "height": 600,
        }
        for a in catalog["albums"]
    ]
    payload = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "art_version": album_art_version(entries, catalog["snapshot_date"]),
        "generated_at": ctx.generated_at,
        "source": "synthetic",
        "license": "presentational only",
        "albums": entries,
    }
    # The real builder stamps its declared input the same way (album_art.py).
    stamp_inputs(payload, lineage_inputs(catalog=catalog))
    ctx.o(rr.ART).parent.mkdir(parents=True, exist_ok=True)
    ctx.o(rr.ART).write_text(json.dumps(payload, indent=2) + "\n")


def _cli(*argv: str) -> None:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert main(list(argv)) == 0, argv


def _build_previous_artifacts(root: Path, onehop: Path, masters: Path, inputs: dict[str, Path]):
    """The currently-published set: round 1 (albums 1-3), built through the same
    CLI builders, plus a schema-v2 daily manifest whose gen-1 points at the
    LIVE rounds file (the real situation before a round)."""
    prev = root / "previous" / "data"
    ctx = rr.Ctx(
        spec={"generated_at": "2026-11-20T00:00:00+00:00", "target_count": 3, "round": 1,
              "parameters": {}},
        today=date(2026, 11, 20), prev=root / "nothing", out=prev, work=root / "w0",
        inputs={k: v for k, v in inputs.items()},
    )  # fmt: skip
    ctx.inputs["approved_pool"] = _pool(root / "pool1.json", [901, 902, 903])
    ctx.inputs["editorial_albums"] = _editorial(root / "ed1.json", [1, 2, 3])
    gen = ctx.generated_at
    o = ctx.o
    shares = ["--max-endpoint-share", "1.0", "--max-bridge-share", "1.0"]
    _cli(
        "build-public-album-catalog", "--onehop-root", str(onehop),
        "--approved-pool", str(ctx.inputs["approved_pool"]),
        "--editorial-albums", str(ctx.inputs["editorial_albums"]),
        "--candidates", str(inputs["candidates"]), "--target-count", "3",
        "--release-format-policy", str(inputs["release_format_policy"]),
        "--masters-root", str(masters),
        "--studio-album-exclusions", str(inputs["studio_album_exclusions"]),
        "--output", str(o(rr.CATALOG)),
    )  # fmt: skip
    _cli("build-album-credit-membership", "--onehop-root", str(onehop), "--catalog",
         str(o(rr.CATALOG)), "--output", str(o(rr.MEMBERSHIP)), "--generated-at", gen)  # fmt: skip
    _cli("build-pathfinding-graph", "--onehop-root", str(onehop), "--catalog", str(o(rr.CATALOG)),
         "--album-credit-membership", str(o(rr.MEMBERSHIP)), "--output", str(o(rr.GRAPH)),
         "--generated-at", gen)  # fmt: skip
    _cli("build-challenge-from-dump", "--onehop-root", str(onehop), "--albums",
         str(o(rr.CATALOG)), "--masters-root", str(masters), "--max-hops", "4",
         "--max-frontier-expansion", "0", "--in-memory-search", "--output",
         str(o(rr.CHALLENGE)))  # fmt: skip
    _cli("build-record-routes", "--onehop-root", str(onehop), "--albums", str(o(rr.CATALOG)),
         "--one-hop-target", "5", "--two-hop-target", "5", *shares,
         "--output-universe", str(o(rr.ROUTES_UNIVERSE)), "--output-rounds",
         str(o(rr.ROUTES_ROUNDS)))  # fmt: skip
    _cli("build-connection-rounds", "--onehop-root", str(onehop), "--albums",
         str(o(rr.CATALOG)), "--one-hop-target", "5", "--two-hop-target", "5", *shares,
         "--output-universe", str(o(rr.GAME_UNIVERSE)), "--output-rounds",
         str(o(rr.GAME_ROUNDS)))  # fmt: skip
    _synthetic_art(ctx)
    _cli("build-evidence-release-registry", "--onehop-root", str(onehop), "--challenge",
         str(o(rr.CHALLENGE)), "--routes-rounds", str(o(rr.ROUTES_ROUNDS)),
         "--pathfinding-graph", str(o(rr.GRAPH)), "--album-art", str(o(rr.ART)), "--catalog",
         str(o(rr.CATALOG)), "--output", str(o(rr.EVIDENCE)), "--generated-at", gen)  # fmt: skip
    _cli("build-prominence", "--pathfinding-graph", str(o(rr.GRAPH)),
         "--evidence-release-registry", str(o(rr.EVIDENCE)), "--output", str(o(rr.PROMINENCE)),
         "--generated-at", gen)  # fmt: skip
    _cli("build-contributor-index", "--challenge", str(o(rr.CHALLENGE)), "--routes-universe",
         str(o(rr.ROUTES_UNIVERSE)), "--routes-rounds", str(o(rr.ROUTES_ROUNDS)), "--catalog",
         str(o(rr.CATALOG)), "--evidence-release-registry", str(o(rr.EVIDENCE)), "--output",
         str(o(rr.CONTRIBUTORS)), "--generated-at", gen)  # fmt: skip
    _cli("build-search-index", "--catalog", str(o(rr.CATALOG)), "--contributor-index",
         str(o(rr.CONTRIBUTORS)), "--output", str(o(rr.SEARCH)), "--generated-at", gen)  # fmt: skip
    _cli("build-album-hop-distances", "--challenge", str(o(rr.CHALLENGE)), "--routes-rounds",
         str(o(rr.ROUTES_ROUNDS)), "--catalog", str(o(rr.CATALOG)), "--contributor-index",
         str(o(rr.CONTRIBUTORS)), "--output", str(o(rr.HOP_DISTANCES)), "--generated-at",
         gen)  # fmt: skip
    # Daily manifest: v1 over the live rounds, then the lossless v2 upgrade (gen-1 -> LIVE).
    v1 = root / "manifest-v1.json"
    _cli("build-connection-daily-manifest", "--rounds", str(o(rr.GAME_ROUNDS)), "--start-date",
         "2026-12-06", "--days", "2", "--output", str(v1), "--generated-at", gen)  # fmt: skip
    _cli("upgrade-connection-daily-manifest-to-v2", "--manifest", str(v1), "--generation-id",
         "gen-1", "--rounds-url", rr.LIVE_ROUNDS_URL, "--output",
         str(o(rr.DAILY_MANIFEST)))  # fmt: skip
    return prev


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("world")
    onehop, masters = _write_corpus(root)
    policy = root / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "kind": "release-format-scoring-index",
                "policy_name": "studio-album-v1",
                "policy_version": 1,
                "schema_version": 1,
                "snapshot_date": SNAPSHOT,
                "allowed_release_ids": [1, 2, 3, 4],
                "allowed_release_count": 4,
                "source_policy_sha256": "deadbeef",
            }
        )
    )
    exclusions = root / "exclusions.json"
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
    candidates = root / "candidates.json"
    candidates.write_text("[]")
    inputs = {
        "onehop_root": onehop,
        "masters_root": masters,
        "release_format_policy": policy,
        "studio_album_exclusions": exclusions,
        "candidates": candidates,
    }
    prev = _build_previous_artifacts(root, onehop, masters, dict(inputs))
    # A pin over the first already-played date of the previous schedule and a
    # budgets file: both are explicit round inputs read by the verify stage.
    from networked_players_contracts import advance_pin

    prev_manifest = json.loads((prev / rr.DAILY_MANIFEST).read_text())
    first_date = min(entry["date"] for entry in prev_manifest["schedule"])
    pin = root / "daily-pin.json"
    pin.write_text(json.dumps(advance_pin(prev_manifest, None, first_date, as_of="2099-01-01")))
    budgets = root / "budgets.json"
    budgets.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "graph_gzip_hard_bytes": 2_500_000,
                "graph_gzip_warn_bytes": 2_000_000,
                "data_total_raw_hard_bytes": 60_000_000,
            }
        )
    )
    inputs = {**inputs, "daily_manifest_pin": pin, "payload_budgets": budgets}
    return {
        "root": root,
        "prev": prev,
        "inputs": inputs,
        "pool": _pool(root / "pool2.json", [901, 902, 903, 904], new_round=2),
        "editorial": _editorial(root / "ed2.json", [1, 2, 3, 4]),
    }


def make_spec(world: dict[str, Any], tmp: Path, name: str = "run", **overrides: Any) -> Path:
    null = {"path": None, "reason": "synthetic round does not use this"}
    inputs: dict[str, Any] = {
        **{k: str(v) for k, v in world["inputs"].items()},
        "approved_pool": str(world["pool"]),
        "editorial_albums": str(world["editorial"]),
        "artist_family_exclusions": null,
        "featured_albums": null,
        "personal_seed": null,
        "graph_rich_selection": null,
        "coverage_gap_candidates": null,
        "album_art_cache_dir": null,
        "round_seed_spec": null,
        "full_corpus_root": null,
        "private_seed": null,
        "editorial_seed": null,
    }
    spec: dict[str, Any] = {
        "schema_version": 1,
        "round": 2,
        "target_count": 4,
        "themes": ["synthetic theme"],
        "generated_at": GENERATED_AT,
        "planned_merge_date": MERGE,
        "daily": {"cutover_lead_days": 3, "new_generation_id": "gen-2", "days": 5},
        "paths": {
            "previous_artifacts_dir": str(world["prev"]),
            "output_dir": str(tmp / name / "public" / "data"),
            "work_dir": str(tmp / name / "work"),
        },
        "inputs": inputs,
        # Targets for routes/guesser are inherited; the challenge's are explicit.
        "parameters": {"challenge": {"max_hops": 4, "max_frontier_expansion": 0}},
    }
    spec.update(overrides)
    path = tmp / f"{name}-spec.json"
    path.write_text(json.dumps(spec, indent=2))
    return path


def _ctx(spec_path: Path, today: str = TODAY, formatter: Any = None) -> rr.Ctx:
    spec = rr.load_spec(spec_path)
    return rr.build_ctx(
        spec,
        today=date.fromisoformat(today),
        formatter=formatter or (lambda files: None),
        art_builder=_synthetic_art,
        log=lambda message: None,
    )


def _versions(out: Path) -> dict[str, str | None]:
    return rr.artifact_versions(out)


# ---------------------------------------------------------------------------


def test_end_to_end_twice_is_deterministic_and_verifies(
    world: dict[str, Any], tmp_path: Path
) -> None:
    formatted: list[list[Path]] = []
    results = []
    for name in ("a", "b"):
        ctx = _ctx(make_spec(world, tmp_path, name), formatter=formatted.append)
        assert rr.run_round(ctx) == 0
        report = (ctx.work / "report.md").read_text()
        assert "Verification: **PASS**" in report
        assert "fourth dream" in report.lower()
        results.append(ctx)
        ok, detail = rr.verify_round(ctx)
        assert ok, detail["problems"]
        assert detail["lineage"]["undeclared_inputs"] == []
        assert detail["lineage"]["partially_declared_inputs"] == {}
    versions_a, versions_b = (_versions(c.out) for c in results)
    assert versions_a == versions_b
    assert all(v for v in versions_a.values())
    assert versions_a != _versions(world["prev"])  # the catalog really changed
    manifest_a = json.loads(results[0].o(rr.DAILY_MANIFEST).read_text())
    assert manifest_a == json.loads(results[1].o(rr.DAILY_MANIFEST).read_text())
    assert [g["generation_id"] for g in manifest_a["generations"]] == ["gen-1", "gen-2"]
    assert manifest_a["generations"][0]["rounds_url"] == "/data/game/generations/gen-1/rounds.json"
    assert manifest_a["generations"][1]["rounds_url"] == rr.LIVE_ROUNDS_URL
    # Already-scheduled dates are untouched.
    prev_manifest = json.loads((world["prev"] / rr.DAILY_MANIFEST).read_text())
    assert manifest_a["schedule"][:2] == prev_manifest["schedule"]
    # The format stage got only formattable, non-ignored files.
    names = {p.relative_to(results[0].out).as_posix() for p in formatted[0]}
    assert rr.CATALOG in names and rr.DAILY_MANIFEST in names and rr.CHALLENGE in names
    assert rr.ROUTES_ROUNDS not in names and rr.CONTRIBUTORS not in names
    assert rr.EVIDENCE not in names and rr.GAME_ROUNDS not in names
    # Builder parameters and their sources are in the report.
    report = (results[0].work / "report.md").read_text()
    assert "record_routes" in report and "(inherited)" in report and "(explicit)" in report


def test_from_stage_restart_matches_uninterrupted(world: dict[str, Any], tmp_path: Path) -> None:
    full = _ctx(make_spec(world, tmp_path, "full"))
    assert rr.run_round(full) == 0
    part = _ctx(make_spec(world, tmp_path, "part"))
    assert rr.run_round(part, to_stage="record-routes") == 0
    assert rr.run_round(part, from_stage="freeze-daily-generation") == 0
    assert _versions(part.out) == _versions(full.out)
    assert json.loads(part.o(rr.DAILY_MANIFEST).read_text()) == json.loads(
        full.o(rr.DAILY_MANIFEST).read_text()
    )


def test_plan_writes_nothing_and_lists_every_stage(
    world: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_path = make_spec(world, tmp_path, "plan")
    ctx = _ctx(spec_path)
    text, failures = rr.plan_round(ctx, rr.select_stages(None, None))
    assert failures == [], failures
    for stage in rr.STAGES:
        # Opt-in stages (supply, re-widen) are outside the default publish sequence.
        assert (f"] {stage.name}:" in text) is not stage.opt_in
    assert "--carry-forward-challenge" in text and "--previous-routes-universe" in text
    assert "--previous-connection-universe" in text and "--approved-pool" in text
    assert "record_routes.two_hop_target = 5 (inherited)" in text
    assert not (tmp_path / "plan").exists()  # neither out nor work dir was created
    # Via the CLI too.
    assert main(["round", "plan", "--spec", str(spec_path), "--today", TODAY]) in (0, 1)
    assert not (tmp_path / "plan").exists()


def test_plan_fails_on_a_missing_input(world: dict[str, Any], tmp_path: Path) -> None:
    path = make_spec(world, tmp_path, "missing")
    spec = json.loads(path.read_text())
    spec["inputs"]["masters_root"] = str(tmp_path / "nope")
    path.write_text(json.dumps(spec))
    _, failures = rr.plan_round(_ctx(path), rr.select_stages(None, None))
    assert any("masters_root" in f and "does not exist" in f for f in failures)
    assert main(["round", "plan", "--spec", str(path), "--today", TODAY]) == 1


@pytest.mark.parametrize("name", ["artist_family_exclusions", "featured_albums", "approved_pool"])
def test_an_absent_policy_input_needs_explicit_null_and_reason(
    world: dict[str, Any], tmp_path: Path, name: str
) -> None:
    path = make_spec(world, tmp_path, "absent")
    spec = json.loads(path.read_text())
    del spec["inputs"][name]
    path.write_text(json.dumps(spec))
    with pytest.raises(rr.RoundError, match=f"inputs.{name} is missing"):
        rr.load_spec(path)
    spec["inputs"][name] = {"path": None}  # null without a reason is not enough
    path.write_text(json.dumps(spec))
    with pytest.raises(rr.RoundError, match="reason"):
        rr.load_spec(path)


def test_null_for_an_input_a_builder_requires_fails_planning(
    world: dict[str, Any], tmp_path: Path
) -> None:
    path = make_spec(world, tmp_path, "nullreq")
    spec = json.loads(path.read_text())
    spec["inputs"]["release_format_policy"] = {"path": None, "reason": "not today"}
    path.write_text(json.dumps(spec))
    _, failures = rr.plan_round(_ctx(path), rr.select_stages(None, None))
    assert any("release_format_policy" in f and "requires it" in f for f in failures)


def test_a_parameter_that_would_use_a_code_default_fails_planning(
    world: dict[str, Any], tmp_path: Path
) -> None:
    path = make_spec(world, tmp_path, "nodefault")
    spec = json.loads(path.read_text())
    spec[
        "parameters"
    ] = {}  # the previous challenge records max_hops, so only frontier is... both inherit
    path.write_text(json.dumps(spec))
    prev = tmp_path / "prev-nobp"
    prev.mkdir()
    for rel in (rr.CHALLENGE, rr.ROUTES_UNIVERSE, rr.GAME_UNIVERSE):
        payload = json.loads((world["prev"] / rel).read_text())
        payload["provenance"].pop("build_parameters", None)
        (prev / rel).parent.mkdir(parents=True, exist_ok=True)
        (prev / rel).write_text(json.dumps(payload))
    spec["paths"]["previous_artifacts_dir"] = str(prev)
    path.write_text(json.dumps(spec))
    _, failures = rr.plan_round(_ctx(path), rr.select_stages(None, None))
    assert any("record_routes.two_hop_target would use the code default" in f for f in failures)


def test_baseline_must_differ_from_output(world: dict[str, Any], tmp_path: Path) -> None:
    path = make_spec(world, tmp_path, "same")
    spec = json.loads(path.read_text())
    spec["paths"]["output_dir"] = spec["paths"]["previous_artifacts_dir"]
    path.write_text(json.dumps(spec))
    _, failures = rr.plan_round(_ctx(path), rr.select_stages(None, None))
    assert any("equals paths.output_dir" in f for f in failures)


def test_freeze_guard_refuses_connection_rounds_until_frozen(
    world: dict[str, Any], tmp_path: Path
) -> None:
    ctx = _ctx(make_spec(world, tmp_path, "guard"))
    assert rr.run_round(ctx, to_stage="album-credit-membership") == 0
    # Starting at connection-rounds with gen-1 still on the live file: refused.
    assert rr.run_round(ctx, from_stage="connection-rounds", to_stage="connection-rounds") == 2
    assert not ctx.o(rr.GAME_ROUNDS).exists()
    stage = next(s for s in rr.STAGES if s.name == "connection-rounds")
    assert any("freeze" in f for f in stage.precheck(ctx, False))  # type: ignore[misc]
    # After the freeze the same stage is allowed.
    assert rr.run_round(ctx, from_stage="record-routes", to_stage="connection-rounds") == 0
    assert ctx.o(rr.GAME_ROUNDS).is_file()
    assert stage.precheck(ctx, False) == []  # type: ignore[misc]


@pytest.mark.parametrize(
    ("lead", "today", "needle"),
    [
        (0, TODAY, "daily.cutover_lead_days"),  # shape: must be >= 1 (cutover after merge)
        (1, TODAY, ""),  # cutover 12-06 is 5 days after today: legal
        (3, "2026-12-07", "before --today"),  # merge date already past
        (3, "2026-12-06", "before --today"),
    ],
)
def test_calendar_refusals(
    world: dict[str, Any], tmp_path: Path, lead: int, today: str, needle: str
) -> None:
    spec = json.loads(make_spec(world, tmp_path, "cal").read_text())
    spec["daily"]["cutover_lead_days"] = lead
    if lead == 0:
        assert any(needle in f for f in rr.validate_spec_shape(spec))
        return
    failures = rr.calendar_failures(spec, today=date.fromisoformat(today))
    if lead == 1:
        assert failures == []  # 12-06 is 5 days after today: legal; the next test tightens it
    else:
        assert any(needle in f for f in failures)


def test_cutover_must_lead_today_by_the_modules_minimum(
    world: dict[str, Any], tmp_path: Path
) -> None:
    spec = json.loads(make_spec(world, tmp_path, "cal2").read_text())
    spec["planned_merge_date"] = "2026-12-01"
    spec["daily"]["cutover_lead_days"] = 1  # cutover 12-02 = today + 1 day
    failures = rr.calendar_failures(spec, today=date(2026, 12, 1))
    assert any("not at least 2 days in the future" in f for f in failures)
    spec["daily"]["cutover_lead_days"] = 2  # cutover 12-03
    assert rr.calendar_failures(spec, today=date(2026, 12, 1)) == []
    # A cutover in the past of --today is refused outright.
    assert rr.calendar_failures(spec, today=date(2026, 12, 4))


def test_run_refuses_when_the_cutover_is_not_in_the_future(
    world: dict[str, Any], tmp_path: Path
) -> None:
    ctx = _ctx(make_spec(world, tmp_path, "late"), today="2026-12-07")
    assert rr.run_round(ctx) == 2
    assert not ctx.out.exists()  # refused before writing anything


def test_manifest_gap_is_refused_before_building(world: dict[str, Any], tmp_path: Path) -> None:
    spec = json.loads(make_spec(world, tmp_path, "gap").read_text())
    spec["daily"]["cutover_lead_days"] = 9  # 12-14, but the schedule ends 12-07
    path = tmp_path / "gap-spec2.json"
    path.write_text(json.dumps(spec))
    _, failures = rr.plan_round(_ctx(path), rr.select_stages(None, None))
    assert any("gap" in f for f in failures)


def test_a_failing_stage_stops_the_run_and_is_named(world: dict[str, Any], tmp_path: Path) -> None:
    messages: list[str] = []
    spec_path = make_spec(world, tmp_path, "fail")
    spec = rr.load_spec(spec_path)
    ctx = rr.build_ctx(
        spec,
        today=date.fromisoformat(TODAY),
        formatter=lambda files: None,
        art_builder=_synthetic_art,
        log=messages.append,
    )
    # An approved pool that does not match the one-hop corpus makes the catalog stage fail.
    ctx.inputs["approved_pool"] = _pool(tmp_path / "bad-pool.json", [901, 902, 903, 777])
    assert rr.run_round(ctx) == 1
    text = "\n".join(messages)
    assert f"[{rr.STAGE_NAMES.index('catalog') + 1}/{len(rr.STAGES)}] catalog: FAILED" in text
    assert "--from-stage catalog" in text
    assert not ctx.o(rr.GRAPH).exists()  # nothing after the failure ran


def test_format_stage_fails_without_prettier_instead_of_skipping(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rr.shutil, "which", lambda name: None)
    spec = rr.load_spec(make_spec(world, tmp_path, "noprettier"))
    ctx = rr.build_ctx(spec, today=date.fromisoformat(TODAY), art_builder=_synthetic_art)
    stage = next(s for s in rr.STAGES if s.name == "format")
    assert any("Node is not on PATH" in f for f in stage.precheck(ctx, True))  # type: ignore[misc]
    with pytest.raises(rr.RoundError, match="Node is not on PATH"):
        rr.default_formatter([Path("x.json")])


def test_prettier_ignore_follows_the_ignore_file() -> None:
    patterns = rr.load_prettier_ignore()
    for rel in (
        rr.ROUTES_ROUNDS,
        rr.GAME_ROUNDS,
        rr.CONTRIBUTORS,
        rr.EVIDENCE,
        "game/generations/gen-1/rounds.json",
        "game/generations/gen-12/rounds.json",
    ):
        assert rr.prettier_ignored(rel, patterns), rel
    for rel in (rr.CATALOG, rr.CHALLENGE, rr.DAILY_MANIFEST, rr.GRAPH, rr.SEARCH):
        assert not rr.prettier_ignored(rel, patterns), rel


def test_check_cutover_is_a_pure_ci_safe_check(world: dict[str, Any], tmp_path: Path) -> None:
    manifest = json.loads((world["prev"] / rr.DAILY_MANIFEST).read_text())
    assert rr.newest_generation_cutover(manifest) == "2026-12-06"
    assert rr.cutover_still_future_failures(manifest, today="2026-12-05") == []
    assert rr.cutover_still_future_failures(manifest, today="2026-12-06")
    path = tmp_path / "m.json"
    path.write_text(json.dumps(manifest))
    assert main(["round", "check-cutover", "--manifest", str(path), "--today", "2026-12-05"]) == 0
    assert main(["round", "check-cutover", "--manifest", str(path), "--today", "2026-12-07"]) == 1


def test_daily_manifest_continuity_detects_a_rewritten_played_date(
    world: dict[str, Any], tmp_path: Path
) -> None:
    ctx = _ctx(make_spec(world, tmp_path, "played"))
    assert rr.run_round(ctx) == 0
    previous = json.loads((world["prev"] / rr.DAILY_MANIFEST).read_text())
    current = json.loads(ctx.o(rr.DAILY_MANIFEST).read_text())
    assert rr.daily_manifest_continuity_failures(previous, current, today=date(2026, 12, 1)) == []
    tampered = copy.deepcopy(current)
    tampered["schedule"][0]["round_id"] = "conn-0000000000"
    failures = rr.daily_manifest_continuity_failures(previous, tampered, today=date(2026, 12, 1))
    assert failures and "2026-12-06" in failures[0]
    ok, detail = rr.verify_round(ctx)
    assert ok, detail["problems"]
    ctx.o(rr.DAILY_MANIFEST).write_text(json.dumps(tampered))
    ok, detail = rr.verify_round(ctx)
    assert not ok


def test_verify_reports_a_stale_artifact(world: dict[str, Any], tmp_path: Path) -> None:
    ctx = _ctx(make_spec(world, tmp_path, "stale"))
    assert rr.run_round(ctx) == 0
    # Replace the challenge with the previous (older catalog) one: lineage/cross-checks fail.
    ctx.o(rr.CHALLENGE).write_text((world["prev"] / rr.CHALLENGE).read_text())
    ok, detail = rr.verify_round(ctx)
    assert not ok and detail["problems"]


def test_committed_example_spec_is_structurally_valid() -> None:
    example = (
        Path(__file__).resolve().parents[3] / "data/albums/rounds/example-synthetic-round.json"
    )
    assert rr.validate_spec_shape(json.loads(example.read_text())) == []


def test_default_formatter_passes_absolute_paths_when_given_relative_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prettier runs with apps/web as its working directory, so a
    repo-relative artifact path must be resolved first or it is looked up
    beneath apps/web/ and the format stage fails on a real round."""
    web_dir = tmp_path / "apps" / "web"
    bin_dir = web_dir / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    seen = tmp_path / "seen.txt"
    fake = bin_dir / "prettier"
    # A stand-in that fails unless every file argument exists from ITS cwd.
    fake.write_text(
        "#!/bin/sh\n"
        'shift\nfor f in "$@"; do [ -f "$f" ] || { echo "missing $f" >&2; exit 3; }; '
        f'echo "$f" >> "{seen}"; done\n'
    )
    fake.chmod(0o755)
    artifact = tmp_path / "out" / "data" / "catalog" / "albums.v1.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}")
    monkeypatch.setattr(rr, "WEB_DIR", web_dir)
    monkeypatch.setattr(rr.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.chdir(tmp_path)

    rr.default_formatter([Path("out/data/catalog/albums.v1.json")])

    assert seen.read_text().split() == [str(artifact.resolve())]


# ---------------------------------------------------------------------------
# Seed supply and post-approval re-widen stages (Campaign Atlas SS)
# ---------------------------------------------------------------------------


def test_opt_in_stages_run_only_when_named() -> None:
    default = [s.name for s in rr.select_stages(None, None)]
    assert "theme-supply" not in default and "onehop-rewiden" not in default
    assert [s.name for s in rr.select_stages(None, None, "theme-supply")] == ["theme-supply"]
    assert [s.name for s in rr.select_stages(None, "theme-supply")] == ["theme-supply"]
    from_rewiden = [s.name for s in rr.select_stages("onehop-rewiden", None)]
    assert from_rewiden[:2] == ["onehop-rewiden", "catalog"]
    assert "theme-supply" not in from_rewiden
    with pytest.raises(rr.RoundError):
        rr.select_stages("catalog", None, "theme-supply")
    # A range out of supply would skip scoring, review and approval: refused.
    for to in (None, "onehop-rewiden", "catalog", "verify"):
        with pytest.raises(rr.RoundError, match="skip scoring"):
            rr.select_stages("theme-supply", to)
    # Supply precedes every builder; re-widen follows the approved pool and precedes the catalog.
    assert rr.STAGE_NAMES.index("theme-supply") < rr.STAGE_NAMES.index("prepare-output")
    assert rr.STAGE_NAMES.index("onehop-rewiden") < rr.STAGE_NAMES.index("catalog")


@pytest.mark.parametrize(
    ("stage", "needed"),
    [
        ("theme-supply", ["round_seed_spec", "full_corpus_root"]),
        ("onehop-rewiden", ["full_corpus_root", "private_seed", "editorial_seed"]),
    ],
)
def test_supply_stages_require_their_inputs_explicitly(
    world: dict[str, Any], tmp_path: Path, stage: str, needed: list[str]
) -> None:
    ctx = _ctx(make_spec(world, tmp_path, "needs"))
    # Null inputs are fine for the default publish range ...
    assert rr.input_failures(ctx, rr.select_stages(None, None)) == []
    # ... and refused, naming the stage, once the stage is selected.
    failures = rr.input_failures(ctx, rr.select_stages(None, None, stage))
    for name in needed:
        assert any(f"inputs.{name} is null" in f and stage in f for f in failures), name


def _supply_world(world: dict[str, Any], tmp_path: Path, name: str) -> tuple[Path, rr.Ctx]:
    from test_theme_supply import ALLOWED, FIXTURE_SPEC, _editorial, _pool, _write_world

    full, masters = _write_world(tmp_path / f"{name}-corpus")
    policy = Path(world["inputs"]["release_format_policy"])
    policy_payload = json.loads(policy.read_text())
    policy_payload["allowed_release_ids"] = ALLOWED
    own_policy = tmp_path / f"{name}-policy.json"
    own_policy.write_text(json.dumps(policy_payload))
    path = make_spec(world, tmp_path, name)
    spec = json.loads(path.read_text())
    spec["paths"]["work_dir"] = str(tmp_path / "local" / name / "work")
    spec["round"] = 99
    spec["target_count"] = 20
    spec["inputs"].update(
        {
            "round_seed_spec": str(FIXTURE_SPEC),
            "full_corpus_root": str(full),
            "masters_root": str(masters),
            "release_format_policy": str(own_policy),
            "editorial_seed": str(_editorial(tmp_path / f"{name}-ed.json")),
            "approved_pool": str(_pool(tmp_path / f"{name}-pool.json", [9100, 9101, 9501])),
        }
    )
    path.write_text(json.dumps(spec))
    return path, _ctx(path)


def test_theme_supply_stage_writes_private_candidates(
    world: dict[str, Any], tmp_path: Path
) -> None:
    _path, ctx = _supply_world(world, tmp_path, "supply")
    text, failures = rr.plan_round(ctx, rr.select_stages(None, None, "theme-supply"))
    assert failures == [], failures
    assert "build-theme-candidates" in text and "--seed-spec" in text
    assert rr.run_round(ctx, only_stage="theme-supply") == 0
    rows = json.loads((ctx.work / rr.THEME_CANDIDATES).read_text())
    eligible = {r["master_id"] for r in rows if r["eligibility"] == "eligible"}
    # The run spec's previous catalog does not publish 9108, so it is a candidate here.
    assert eligible == {9100, 9101, 9108, 9500, 9501}
    assert not ctx.out.exists()  # a supply run never touches the public output


def test_theme_supply_refuses_a_tracked_work_dir_and_a_mismatched_seed_spec(
    world: dict[str, Any], tmp_path: Path
) -> None:
    path, _ = _supply_world(world, tmp_path, "refuse")
    spec = json.loads(path.read_text())
    spec["paths"]["work_dir"] = str(tmp_path / "plainwork")  # not under local/
    spec["round"] = 5  # does not match the seed spec's round
    path.write_text(json.dumps(spec))
    _, failures = rr.plan_round(_ctx(path), rr.select_stages(None, None, "theme-supply"))
    assert any("local/" in f for f in failures)
    assert any("does not match the run spec" in f for f in failures)
    assert rr.run_round(_ctx(path), only_stage="theme-supply") == 2


def test_rewiden_stage_replaces_the_onehop_corpus_for_approved_albums(
    world: dict[str, Any], tmp_path: Path
) -> None:
    import pyarrow.dataset as ds

    from networked_players_catalog.discogs.seed import SeedManifest

    path, ctx = _supply_world(world, tmp_path, "rewiden")
    onehop = tmp_path / "onehop-parent" / f"snapshot={SNAPSHOT}"
    shutil.copytree(ctx.inp("onehop_root"), onehop)
    seed = tmp_path / "private-seed.json"
    SeedManifest(1, "synthetic", "2026-12-01T00:00:00+00:00", [1]).write(seed)
    spec = json.loads(path.read_text())
    spec["inputs"]["private_seed"] = str(seed)
    spec["inputs"]["onehop_root"] = str(onehop)
    path.write_text(json.dumps(spec))
    ctx = _ctx(path)
    text, failures = rr.plan_round(ctx, rr.select_stages(None, None, "onehop-rewiden"))
    assert failures == [], failures
    assert "--additional-seed" in text and "--overwrite" in text
    before = {r["master_id"] for r in ds.dataset(onehop / "table=releases").to_table().to_pylist()}
    assert not {9100, 9101, 9501} & before  # the synthetic corpus lacks the approved albums
    assert rr.run_round(ctx, only_stage="onehop-rewiden") == 0
    after = {r["master_id"] for r in ds.dataset(onehop / "table=releases").to_table().to_pylist()}
    assert {9100, 9101, 9501} <= after  # approved albums are now inside the corpus
    # The corpus must keep its name, or later stages would read a stale directory.
    spec["inputs"]["onehop_root"] = str(onehop.parent / "snapshot=19990101")
    path.write_text(json.dumps(spec))
    _, failures = rr.plan_round(_ctx(path), rr.select_stages(None, None, "onehop-rewiden"))
    assert any("must be named" in f or "does not exist" in f for f in failures)


def test_rewiden_reports_a_corpus_without_a_manifest(world: dict[str, Any], tmp_path: Path) -> None:
    path, _ = _supply_world(world, tmp_path, "nomanifest")
    spec = json.loads(path.read_text())
    empty = tmp_path / "empty-corpus"
    empty.mkdir()
    spec["inputs"]["full_corpus_root"] = str(empty)
    path.write_text(json.dumps(spec))
    ctx = _ctx(path)
    failures = rr.evaluate_preconditions(
        ctx, rr.select_stages(None, None, "onehop-rewiden"), planning=True
    )
    assert any("has no manifest.json" in f for f in failures)
