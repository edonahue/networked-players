"""Review-packet generator (Campaign Atlas RP): synthetic fixtures only."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog import review_packet as rp
from networked_players_catalog.cli import main
from networked_players_contracts.approved_pool import approved_pool_failures
from networked_players_contracts.catalog import VALID_SELECTION_SOURCES

REPO_ROOT = Path(__file__).resolve().parents[3]
HOSTILE = "</script><img src=x onerror=alert(1)>"

ROUND_ARGS = ["--mode", "round", "--round", "3"]


def _row(master_id: int, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "master_id": master_id,
        "artist_id": 10,
        "artist_name": "Synthetic Artist",
        "sample_title": f"Synthetic Album {master_id}",
        "eligibility": "eligible",
        "main_release_id": master_id * 10,
        "main_release_selection_reason": "ok",
        "roster_size": 5,
        "roster_artist_ids": [1, 2, 3, 4, 5],
        "overlap_existing": 2,
        "new_performers": 3,
        "new_performer_density": 0.6,
        "editorial": 0,
        "in_private_seed": 1,
        "bridge_span": 4,
        "coverage_delta": 1,
    }
    row.update(extra)
    return row


def _scored() -> dict[str, Any]:
    return {
        "candidate_count": 3,
        "eligible_count": 2,
        "candidates": [
            _row(101, sample_title=HOSTILE, editorial=1),
            _row(102),
            _row(103, eligibility="curated_master_exclusion", roster_size=None, bridge_span=None),
        ],
    }


def _write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def _embedded(html: str) -> dict[str, Any]:
    match = re.search(
        r'<script type="application/json" id="packet-data">(.*?)</script>', html, re.S
    )
    assert match
    return json.loads(match.group(1))  # type: ignore[no-any-return]


def _round_args(tmp_path: Path, out: Path) -> list[str]:
    scored = _write(tmp_path / "in.json", _scored())
    return [
        "build-review-packet",
        *ROUND_ARGS,
        "--scored-candidates",
        str(scored),
        "--output",
        str(out),
    ]


def _round_html(tmp_path: Path, name: str = "a") -> str:
    out = tmp_path / "local" / f"{name}.html"
    assert main(_round_args(tmp_path, out)) == 0
    return out.read_text()


def _study() -> dict[str, Any]:
    albums = [
        {"id": "a1", "title": "One", "artist": "X", "year": 1970},
        {"id": "a2", "title": HOSTILE, "artist": "Y", "year": 1975},
    ]
    return {
        "qualifying_clusters": [
            {
                "album_count": 2,
                "artist_count": 2,
                "albums": albums,
                "bridge_players": [{"name": "Player P", "album_count": 2}],
                "internal_density": 1.0,
                "year_min": 1970,
                "year_max": 1975,
                "year_span": 5,
            }
        ]
    }


def test_round_packet_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    first = _round_html(tmp_path, "a")
    second = _round_html(tmp_path, "b")
    assert first == second
    data = _embedded(first)
    assert data["mode"] == "round" and data["round"] == 3
    assert [r["master_id"] for r in data["rows"]] == [101, 102, 103]
    assert data["rows"][0]["title"] == HOSTILE
    assert data["rows"][2]["eligibility"] == "curated_master_exclusion"
    assert data["rows"][2]["roster_size"] is None
    assert set(data["public_selection_sources"]) == set(VALID_SELECTION_SOURCES)


def test_private_seed_flag_never_reaches_the_page(tmp_path: Path) -> None:
    html = _round_html(tmp_path)
    assert "in_private_seed" not in html
    assert "personal" not in json.dumps(_embedded(html)["rows"])


def test_hostile_strings_are_escaped(tmp_path: Path) -> None:
    html = _round_html(tmp_path)
    assert HOSTILE not in html
    assert "<img" not in html
    assert html.count("</script>") == 2  # data block + code block only
    scored = {"candidates": [_row(5, artist_name="<b>&amp;</b>")]}
    page = rp.render_html(rp.build_round_data(scored, round_number=1))
    assert "<b>" not in page


def test_page_is_offline(tmp_path: Path) -> None:
    for html in (_round_html(tmp_path), rp.render_html(rp.build_collection_data(_study()))):
        assert "http://" not in html and "https://" not in html
        assert not re.search(r"<(link|img|iframe|object|embed|video|audio|source)\b", html)
        # Outside the (escaped, inert) JSON data block, no fetch-capable attribute.
        markup = re.sub(r'(<script type="application/json".*?</script>)', "", html, flags=re.S)
        assert not re.search(r"\b(src|href|action)=", markup)
        assert "innerHTML" not in html and "fetch(" not in html and "XMLHttpRequest" not in html


def test_collection_mode_round_trips(tmp_path: Path) -> None:
    study = _write(tmp_path / "study.json", _study())
    out = tmp_path / "data" / "private" / "c.html"
    argv = ["build-review-packet", "--mode", "collection", "--study", str(study)]
    assert main([*argv, "--output", str(out)]) == 0
    data = _embedded(out.read_text())
    assert data["mode"] == "collection"
    cluster = data["clusters"][0]
    assert cluster["albums"][1]["title"] == HOSTILE
    assert cluster["bridge_players"] == [{"name": "Player P", "album_count": 2}]
    assert cluster["year_span"] == 5
    assert HOSTILE not in out.read_text()


def test_generated_at_is_only_an_explicit_label(tmp_path: Path) -> None:
    out = tmp_path / "local" / "x.html"
    assert main([*_round_args(tmp_path, out), "--generated-at", "label-1"]) == 0
    assert "label-1" in out.read_text()
    # The label does not change the progress key.
    assert (
        _embedded(out.read_text())["input_hash"] == _embedded(_round_html(tmp_path))["input_hash"]
    )


@pytest.mark.parametrize(
    "relative",
    [
        "apps/web/public/x.html",
        "docs/x.html",
        "x.html",
        "local/../apps/web/public/x.html",
        "locally/x.html",
        "data/x.html",
    ],
)
def test_refuses_output_outside_private_dirs(tmp_path: Path, relative: str) -> None:
    target = tmp_path / relative
    assert main(_round_args(tmp_path, target)) == 2
    assert not target.exists()


def test_accepted_directories_are_git_ignored() -> None:
    for path in ("local/x.html", "data/private/x.html"):
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, check=False)
        assert result.returncode == 0, path
    rp.require_review_output(REPO_ROOT / "local" / "x.html")
    with pytest.raises(rp.ReviewPacketError):
        rp.require_review_output(REPO_ROOT / "apps" / "web" / "public" / "x.html")


def test_already_published_and_pool_flags() -> None:
    catalog = {"albums": [{"master_id": 102}]}
    pool = {"albums": [{"master_id": 103, "round": 0, "selection_source": "editorial"}]}
    data = rp.build_round_data(_scored(), round_number=1, catalog=catalog, approved_pool=pool)
    assert [r["already_published"] for r in data["rows"]] == [False, True, True]


def test_review_packet_supplies_year_lane_and_public_source() -> None:
    entry = {"master_id": 102, "bucket": "personal", "year": 1999, "title": "t", "artist": "a"}
    row = rp.build_round_data(_scored(), round_number=1, review_packet={"entries": [entry]})[
        "rows"
    ][1]
    assert (row["year"], row["lane"], row["default_source"]) == (1999, "personal", "editorial")


def test_public_sources_match_contract() -> None:
    assert set(rp.PUBLIC_SELECTION_SOURCES) == set(VALID_SELECTION_SOURCES)


def test_bad_input_is_an_error() -> None:
    with pytest.raises(rp.ReviewPacketError):
        rp.build_round_data({"candidates": [_row(1), _row(1)]}, round_number=0)
    with pytest.raises(rp.ReviewPacketError):
        rp.build_round_data({"candidates": [{"sample_title": "x"}]}, round_number=0)
    with pytest.raises(rp.ReviewPacketError):
        rp.build_collection_data({"clusters": []})


# ---- page logic, exercised under Node against the script embedded in a real packet ----

_NODE_DRIVER = r"""
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const ctx = {}; vm.createContext(ctx); vm.runInContext(scripts[0][1], ctx);
const core = ctx.__RP_CORE__;
const data = JSON.parse(/id="packet-data">([\s\S]*?)<\/script>/.exec(html)[1]);
const PUB = data.public_selection_sources;
const out = {};
const decisions = {101: {status: "approved"}, 102: {status: "rejected"}, 103: {status: "deferred"}};
out.additions = core.buildAdditions(data.rows, decisions, {102: "graph_rich"}, 3, PUB);
const refuse = (fn) => { try { fn(); return false; } catch (e) { return e.message; } };
const ok = {master_id: 1, round: 1, selection_source: "editorial"};
out.extra = refuse(() => core.validateEntries([{...ok, score: 3}], PUB));
out.private = refuse(() => core.validateEntries([{...ok, selection_source: "personal_editorial"}], PUB));
out.missing = refuse(() => core.validateEntries([{master_id: 1, round: 1}], PUB));
out.dup = refuse(() => core.validateEntries([ok, ok], PUB));
out.published = refuse(() => core.buildAdditions([{master_id: 9, already_published: true, default_source: "editorial"}], {9: {status: "approved"}}, {}, 1, PUB));
out.notes = core.buildRoundNotes(data, decisions, {}, {101: "hi"});
const cdata = {input_hash: "h", clusters: [{index: 0, albums: [{id: "a", title: "A", artist: "X", year: 1}, {id: "b", title: "B", artist: "Y", year: 2}]}, {index: 1, albums: [{id: "c", title: "C", artist: "Z", year: 3}]}]};
out.collection = core.buildCollectionSelection(cdata, {0: {status: "keep", title: "T", note: "N", dropped: {b: true}}, 1: {status: "drop"}});
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_export_logic_under_node(tmp_path: Path) -> None:
    page = tmp_path / "local" / "p.html"
    page.parent.mkdir()
    page.write_text(rp.render_html(rp.build_round_data(_scored(), round_number=3)))
    driver = tmp_path / "driver.js"
    driver.write_text(_NODE_DRIVER)
    done = subprocess.run(
        ["node", str(driver), str(page)], capture_output=True, text=True, check=True
    )
    out = json.loads(done.stdout)

    # Only approved items, only the three public fields; source override honoured.
    assert out["additions"] == [{"master_id": 101, "round": 3, "selection_source": "editorial"}]
    assert "refusing to export entry" in out["extra"]
    assert "non-public selection_source" in out["private"]
    assert out["missing"] and "refusing" in out["missing"]
    assert "duplicate" in out["dup"]
    assert "already published" in out["published"]
    assert out["notes"]["private"] is True
    assert [d["status"] for d in out["notes"]["decisions"]] == ["approved", "rejected", "deferred"]
    assert out["notes"]["decisions"][0]["note"] == "hi"
    coll = out["collection"]
    assert coll["private"] is True
    assert [r["id"] for r in coll["clusters"][0]["kept_records"]] == ["a"]
    assert coll["clusters"][0]["working_title"] == "T"
    assert coll["clusters"][1]["kept_records"] == []

    # The exported additions append to a synthetic pool the real contract accepts.
    pool: dict[str, Any] = {
        "schema_version": 1,
        "note": "synthetic",
        "albums": [{"master_id": 50, "round": 0, "selection_source": "editorial"}],
    }
    pool["albums"] = sorted(pool["albums"] + out["additions"], key=lambda a: a["master_id"])
    assert approved_pool_failures(pool) == []
    bad = {**pool, "albums": [pool["albums"][0], {**pool["albums"][1], "score": 1}]}
    assert approved_pool_failures(bad)
