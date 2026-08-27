"""CLI round-trip for `build-expansion-review-packet` -- combines Bucket
A/B/C source files into one review packet. Packet-assembly logic is
unit-tested in packages/catalog/tests/test_expansion_review.py; this pins
the CLI wiring and the data/private/ output guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import _require_private_only_output, main


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


SNAPSHOT = "20260601"


def test_builds_a_packet_from_real_files(tmp_path: Path) -> None:
    catalog = _write(
        tmp_path / "albums.v1.json",
        {"snapshot_date": SNAPSHOT, "albums": [{"master_id": 1}]},
    )
    personal_seed = _write(
        tmp_path / "editorial-seed.json",
        {
            "snapshot_date": SNAPSHOT,
            "albums": [{"master_id": 10, "artist": "A", "title": "Alpha"}],
        },
    )
    graph_rich = _write(
        tmp_path / "graph-rich.json",
        {
            "snapshot_date": SNAPSHOT,
            "selected": [{"master_id": 20, "artist_name": "B", "sample_title": "Beta"}],
        },
    )
    coverage_gap = _write(
        tmp_path / "coverage-gap.json",
        {
            "snapshot_date": SNAPSHOT,
            "candidates": [
                {
                    "master_id": 30,
                    "artist": "C",
                    "title": "Gamma",
                    "gap_dimension": "genres",
                    "gap_bucket": "Reggae",
                    "gap_rationale": "zero representation",
                }
            ],
        },
    )
    output = tmp_path / "data" / "private" / "catalog-expansion" / "review.json"

    exit_code = main(
        [
            "build-expansion-review-packet",
            "--catalog",
            str(catalog),
            "--personal-seed",
            str(personal_seed),
            "--graph-rich-selection",
            str(graph_rich),
            "--coverage-gap-candidates",
            str(coverage_gap),
            "--generated-at",
            "2026-08-27T00:00:00+00:00",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text())
    assert payload["snapshot_date"] == SNAPSHOT
    assert payload["proposed_addition_count"] == 3
    assert payload["bucket_counts"] == {"personal": 1, "graph_rich": 1, "coverage_gap": 1}


def test_a_mismatched_source_snapshot_is_refused(tmp_path: Path) -> None:
    catalog = _write(tmp_path / "albums.v1.json", {"snapshot_date": SNAPSHOT, "albums": []})
    personal_seed = _write(
        tmp_path / "editorial-seed.json", {"snapshot_date": "20200101", "albums": []}
    )
    graph_rich = _write(tmp_path / "graph-rich.json", {"snapshot_date": SNAPSHOT, "selected": []})
    coverage_gap = _write(
        tmp_path / "coverage-gap.json", {"snapshot_date": SNAPSHOT, "candidates": []}
    )
    output = tmp_path / "data" / "private" / "catalog-expansion" / "review.json"

    with pytest.raises(ValueError, match="mismatched snapshot_date"):
        main(
            [
                "build-expansion-review-packet",
                "--catalog",
                str(catalog),
                "--personal-seed",
                str(personal_seed),
                "--graph-rich-selection",
                str(graph_rich),
                "--coverage-gap-candidates",
                str(coverage_gap),
                "--generated-at",
                "2026-08-27T00:00:00+00:00",
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


def test_refuses_to_write_outside_data_private(tmp_path: Path) -> None:
    catalog = _write(tmp_path / "albums.v1.json", {"albums": []})
    personal_seed = _write(tmp_path / "editorial-seed.json", {"albums": []})
    graph_rich = _write(tmp_path / "graph-rich.json", {"selected": []})
    coverage_gap = _write(tmp_path / "coverage-gap.json", {"candidates": []})
    output = tmp_path / "local" / "research" / "review.json"  # local/, not data/private/

    with pytest.raises(ValueError, match="refuses to write outside data/private/"):
        main(
            [
                "build-expansion-review-packet",
                "--catalog",
                str(catalog),
                "--personal-seed",
                str(personal_seed),
                "--graph-rich-selection",
                str(graph_rich),
                "--coverage-gap-candidates",
                str(coverage_gap),
                "--generated-at",
                "2026-08-27T00:00:00+00:00",
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


@pytest.mark.parametrize(
    "output_name",
    [
        "data/private/catalog-expansion/review.json",
        "data/private/../../apps/web/public/data/review.json",
        "apps/web/public/data/review.json",
        "data-private-lookalike/review.json",
    ],
)
def test_require_private_only_output_matches_real_path_components(
    tmp_path: Path, output_name: str
) -> None:
    output = tmp_path / output_name
    should_pass = output_name.startswith("data/private/catalog-expansion")
    if should_pass:
        _require_private_only_output(output, command="test", why="test")
    else:
        with pytest.raises(ValueError, match="refuses to write outside data/private/"):
            _require_private_only_output(output, command="test", why="test")
