from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.discogs.parquet import SCHEMAS

SNAPSHOT_DATE = "20260601"


def write_synthetic_dataset(
    root: Path,
    *,
    release_rows: list[dict[str, Any]],
    credit_rows: list[dict[str, Any]],
    track_rows: list[dict[str, Any]] | None = None,
) -> Path:
    """A real, tiny, schema-conformant parsed-snapshot-shaped dataset --
    mirrors packages/graph-core/tests/conftest.py's helper of the same
    name (kept local rather than cross-package-imported, matching how
    other test suites in this monorepo already accept small per-package
    fixture duplication)."""
    (root / "table=releases").mkdir(parents=True)
    (root / "table=credits").mkdir(parents=True)
    (root / "table=tracks").mkdir(parents=True)

    pq.write_table(
        pa.Table.from_pylist(release_rows, schema=SCHEMAS["releases"]),
        root / "table=releases" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(credit_rows, schema=SCHEMAS["credits"]),
        root / "table=credits" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(track_rows or [], schema=SCHEMAS["tracks"]),
        root / "table=tracks" / "part-00000.parquet",
    )
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 3, "snapshot_date": SNAPSHOT_DATE})
    )
    return root


def _release(release_id: int, title: str, *, released: str | None = None) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": released,
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
    }


def _credit(
    release_id: int,
    *,
    artist_id: int | None,
    name: str,
    scope: str = "release_artist",
    is_linked: bool = True,
    playable_identity: bool = True,
    role_text: str | None = None,
    track_index: int | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": None if track_index is None else str(track_index),
        "track_position": None if track_index is None else str(track_index + 1),
        "track_title": None if track_index is None else f"Track {track_index + 1}",
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": name,
        "anv": None,
        "join_text": None,
        "role_text": role_text,
        "credited_tracks_text": None,
        "is_linked": is_linked,
        "playable_identity": playable_identity,
    }


def _performed(release_id: int, *, artist_id: int, name: str) -> list[dict[str, Any]]:
    return [
        _credit(release_id, artist_id=artist_id, name=name, scope="release_artist"),
        _credit(
            release_id,
            artist_id=artist_id,
            name=name,
            scope="track_artist",
            role_text=None,
            track_index=0,
        ),
    ]


# A small, real-shaped 3-artist/3-release fixture: Jane's own two albums
# plus one album where she's a guest, sharing personnel with Bob and Cara.
FIXTURE_RELEASES = [
    _release(1, "Jane's First Album", released="1990"),
    _release(2, "Jane's Second Album", released="1993"),
    _release(3, "A Bob Solo Record", released="1995"),
]

FIXTURE_CREDITS = [
    *_performed(1, artist_id=100, name="Jane"),
    *_performed(1, artist_id=200, name="Bob"),
    *_performed(2, artist_id=100, name="Jane"),
    *_performed(2, artist_id=300, name="Cara"),
    *_performed(3, artist_id=200, name="Bob"),
]


@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    root = tmp_path / "snapshot=20260601"
    return write_synthetic_dataset(root, release_rows=FIXTURE_RELEASES, credit_rows=FIXTURE_CREDITS)
