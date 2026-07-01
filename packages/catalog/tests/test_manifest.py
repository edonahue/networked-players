from pathlib import Path

import pytest

from networked_players_catalog.discogs.manifest import DumpKind, SnapshotManifest, build_manifest


def test_manifest_has_all_four_objects(tmp_path: Path) -> None:
    manifest = build_manifest("20260501", terms_reviewed_at="2026-06-29")
    assert [item.kind for item in manifest.objects] == [kind.value for kind in DumpKind]
    assert manifest.object_for(DumpKind.RELEASES).filename == "discogs_20260501_releases.xml.gz"

    path = tmp_path / "manifest.json"
    manifest.write(path)
    assert SnapshotManifest.read(path) == manifest


def test_manifest_rejects_non_monthly_date() -> None:
    with pytest.raises(ValueError, match="first day"):
        build_manifest("20260515", terms_reviewed_at="2026-06-29")


def test_object_url_uses_query_string_download_scheme() -> None:
    # data.discogs.com serves objects via a query-string download endpoint, not a
    # literal path -- confirmed against the real host 2026-07-01, since the old
    # direct-path S3 scheme now returns a bucket-level AccessDenied.
    manifest = build_manifest("20260501", terms_reviewed_at="2026-06-29")
    releases = manifest.object_for(DumpKind.RELEASES)
    assert releases.url == (
        "https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20260501_releases.xml.gz"
    )
