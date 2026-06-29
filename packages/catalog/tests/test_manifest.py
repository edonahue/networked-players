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
