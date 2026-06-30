"""End-to-end wiring test for the CLI: manifest -> parse-releases -> validate.

Runs fully offline against the synthetic fixture. The `download` command is
network-dependent and is covered by test_download.py, so it is exercised there
rather than mocked here. This test guards against the four-command pipeline
losing its wiring as other packages come online.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from networked_players_catalog.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "releases.xml"
SNAPSHOT = "20260501"


def _gzip_fixture(destination: Path) -> Path:
    """Write the plain XML fixture out as gzip, mirroring a real dump filename."""
    gz_path = destination / f"discogs_{SNAPSHOT}_releases.xml.gz"
    gz_path.write_bytes(gzip.compress(FIXTURE.read_bytes()))
    return gz_path


def test_cli_pipeline_manifest_parse_validate(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    output_root = tmp_path / "processed"
    releases_gz = _gzip_fixture(tmp_path)

    # 1. manifest
    assert main(["manifest", "--snapshot", SNAPSHOT, "--output", str(manifest_path)]) == 0
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    kinds = {obj["kind"] for obj in manifest["objects"]}
    assert {"artists", "labels", "masters", "releases"} <= kinds
    capsys.readouterr()

    # 2. parse-releases (gzip branch)
    assert (
        main(
            [
                "parse-releases",
                "--input",
                str(releases_gz),
                "--snapshot",
                SNAPSHOT,
                "--source-url",
                "https://example.invalid/synthetic/releases.xml.gz",
                "--output-root",
                str(output_root),
            ]
        )
        == 0
    )
    dataset = output_root / f"snapshot={SNAPSHOT}"
    assert (dataset / "manifest.json").exists()
    for table in ("releases", "tracks", "credits"):
        assert list((dataset / f"table={table}").glob("*.parquet")), f"missing {table} parquet"
    capsys.readouterr()

    # 3. validate — raises on any invariant failure, so reaching exit 0 means clean.
    assert main(["validate", "--dataset", str(dataset)]) == 0
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["release_rows"] == 2
    assert metrics["distinct_release_ids"] == 2
    assert metrics["track_rows"] >= 4  # 3 tracks (incl. nested) on 101, 1 on 102
    assert metrics["credit_rows"] > 0
    assert metrics["orphan_tracks"] == 0
    assert metrics["orphan_credits"] == 0
