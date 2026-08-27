"""CLI round-trip for `select-graph-rich-candidates` -- Phase 7 Bucket B's
selection tool. The marginal-value math itself (credit_edges_sql reuse,
clique detection, tie-breaking, artist-uniqueness enforcement) is thoroughly
unit-tested with hand-verified expectations in
packages/graph-core/tests/test_marginal_evaluation.py; this pins the CLI
wiring only: baseline-release/artist-id union from two input files, the
--dataset/--baseline-catalog snapshot cross-check, output shape, and the
local-only guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.parquet import write_release_dataset
from networked_players_catalog.discogs.releases import iter_releases

FIXTURE = Path(__file__).parent / "fixtures" / "onehop_releases.xml"
SNAPSHOT = "20260501"


def _write_full_dataset(tmp_path: Path) -> Path:
    source_url = "https://example.test/discogs_20260501_releases.xml.gz"
    records = iter_releases(FIXTURE, snapshot_date=SNAPSHOT, source_url=source_url)
    write_release_dataset(
        records,
        tmp_path / "full",
        snapshot_date=SNAPSHOT,
        source_url=source_url,
        chunk_releases=2,
    )
    return tmp_path / "full" / f"snapshot={SNAPSHOT}"


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_selects_by_score_when_marginal_value_ties_and_unions_both_baselines(
    tmp_path: Path,
) -> None:
    dataset = _write_full_dataset(tmp_path)

    baseline_catalog = _write_json(
        tmp_path / "albums.v1.json",
        {
            "snapshot_date": SNAPSHOT,
            "albums": [{"main_release_id": 101, "artist_id": 11}],
        },
    )
    additional_baseline = _write_json(
        tmp_path / "editorial-seed.json",
        {
            "snapshot_date": SNAPSHOT,
            "albums": [{"main_release_id": 105, "artist_id": 98}],
        },
    )
    finalists_path = _write_json(
        tmp_path / "finalists.json",
        [
            {"master_id": 1, "main_release_id": 103, "artist_id": 50, "score": 5},
            {"master_id": 2, "main_release_id": 104, "artist_id": 99, "score": 50},
        ],
    )
    output = tmp_path / "local" / "research" / "graph-rich-selection.json"

    exit_code = main(
        [
            "select-graph-rich-candidates",
            "--dataset",
            str(dataset),
            "--baseline-catalog",
            str(baseline_catalog),
            "--additional-baseline",
            str(additional_baseline),
            "--finalists",
            str(finalists_path),
            "--count",
            "1",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0

    payload = json.loads(output.read_text())
    assert payload["snapshot_date"] == SNAPSHOT
    assert payload["baseline_release_count"] == 2  # 101 (catalog) + 105 (editorial)
    assert payload["baseline_artist_count"] == 2  # 11 + 98
    assert payload["finalist_count"] == 2
    assert payload["requested_count"] == 1
    assert payload["selected_count"] == 1
    # Neither finalist's release forms a real edge against this baseline in
    # this fixture (confirmed: no explicit track-artist credits on either
    # release's single track), so marginal value ties at zero for both --
    # the higher declared score must win the tie.
    selected = payload["selected"][0]
    assert selected["master_id"] == 2
    assert selected["marginal_new_edges"] == 0
    assert selected["marginal_new_contributors"] == 0


def test_additional_baseline_is_optional(tmp_path: Path) -> None:
    dataset = _write_full_dataset(tmp_path)
    baseline_catalog = _write_json(
        tmp_path / "albums.v1.json",
        {"snapshot_date": SNAPSHOT, "albums": [{"main_release_id": 101, "artist_id": 11}]},
    )
    finalists_path = _write_json(
        tmp_path / "finalists.json", [{"master_id": 1, "main_release_id": 103, "artist_id": 50}]
    )
    output = tmp_path / "local" / "out.json"

    exit_code = main(
        [
            "select-graph-rich-candidates",
            "--dataset",
            str(dataset),
            "--baseline-catalog",
            str(baseline_catalog),
            "--finalists",
            str(finalists_path),
            "--count",
            "1",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text())
    assert payload["baseline_release_count"] == 1
    assert payload["baseline_artist_count"] == 1


def test_a_finalist_already_represented_in_the_baseline_is_excluded(tmp_path: Path) -> None:
    """CLI-level proof that baseline artist_ids actually reach the selector:
    a finalist whose artist_id matches the baseline catalog's own artist
    must never be selected, no matter its score."""
    dataset = _write_full_dataset(tmp_path)
    baseline_catalog = _write_json(
        tmp_path / "albums.v1.json",
        {"snapshot_date": SNAPSHOT, "albums": [{"main_release_id": 101, "artist_id": 50}]},
    )
    finalists_path = _write_json(
        tmp_path / "finalists.json",
        [{"master_id": 1, "main_release_id": 103, "artist_id": 50, "score": 999}],
    )
    output = tmp_path / "local" / "out.json"

    exit_code = main(
        [
            "select-graph-rich-candidates",
            "--dataset",
            str(dataset),
            "--baseline-catalog",
            str(baseline_catalog),
            "--finalists",
            str(finalists_path),
            "--count",
            "1",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text())
    assert payload["selected"] == []


def test_dataset_baseline_catalog_snapshot_mismatch_is_refused(tmp_path: Path) -> None:
    dataset = _write_full_dataset(tmp_path)
    baseline_catalog = _write_json(
        tmp_path / "albums.v1.json",
        {"snapshot_date": "20200101", "albums": []},
    )
    finalists_path = _write_json(tmp_path / "finalists.json", [])
    output = tmp_path / "local" / "out.json"

    with pytest.raises(ValueError, match="mismatched-snapshot"):
        main(
            [
                "select-graph-rich-candidates",
                "--dataset",
                str(dataset),
                "--baseline-catalog",
                str(baseline_catalog),
                "--finalists",
                str(finalists_path),
                "--count",
                "1",
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


def test_dataset_additional_baseline_snapshot_mismatch_is_refused(tmp_path: Path) -> None:
    dataset = _write_full_dataset(tmp_path)
    baseline_catalog = _write_json(
        tmp_path / "albums.v1.json", {"snapshot_date": SNAPSHOT, "albums": []}
    )
    additional_baseline = _write_json(
        tmp_path / "editorial-seed.json", {"snapshot_date": "20200101", "albums": []}
    )
    finalists_path = _write_json(tmp_path / "finalists.json", [])
    output = tmp_path / "local" / "out.json"

    with pytest.raises(ValueError, match="mismatched-snapshot"):
        main(
            [
                "select-graph-rich-candidates",
                "--dataset",
                str(dataset),
                "--baseline-catalog",
                str(baseline_catalog),
                "--additional-baseline",
                str(additional_baseline),
                "--finalists",
                str(finalists_path),
                "--count",
                "1",
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


def test_refuses_to_write_outside_local(tmp_path: Path) -> None:
    dataset = _write_full_dataset(tmp_path)
    baseline_catalog = _write_json(
        tmp_path / "albums.v1.json", {"snapshot_date": SNAPSHOT, "albums": []}
    )
    finalists_path = _write_json(tmp_path / "finalists.json", [])
    output = tmp_path / "apps" / "web" / "public" / "data" / "selection.json"

    with pytest.raises(ValueError, match="refuses to write outside local/"):
        main(
            [
                "select-graph-rich-candidates",
                "--dataset",
                str(dataset),
                "--baseline-catalog",
                str(baseline_catalog),
                "--finalists",
                str(finalists_path),
                "--count",
                "1",
                "--output",
                str(output),
            ]
        )
    assert not output.exists()
