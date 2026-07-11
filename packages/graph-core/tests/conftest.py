from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from networked_players_catalog.discogs.parquet import MASTER_SCHEMAS, SCHEMAS

SNAPSHOT_DATE = "20260601"


def write_synthetic_dataset(
    root: Path,
    *,
    release_rows: list[dict[str, Any]],
    credit_rows: list[dict[str, Any]],
    track_rows: list[dict[str, Any]] | None = None,
) -> Path:
    """Write a real, tiny, schema-conformant one-hop-shaped dataset for graph-core tests."""
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
        json.dumps(
            {
                "snapshot_date": SNAPSHOT_DATE,
                "counts": {
                    "releases": len(release_rows),
                    "credits": len(credit_rows),
                    "tracks": len(track_rows or []),
                },
                "expansion": {"source_snapshot_date": SNAPSHOT_DATE},
            }
        )
    )
    return root


def write_synthetic_masters(root: Path, *, master_rows: list[dict[str, Any]]) -> Path:
    (root / "table=masters").mkdir(parents=True)
    (root / "table=master_artists").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(master_rows, schema=MASTER_SCHEMAS["masters"]),
        root / "table=masters" / "part-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([], schema=MASTER_SCHEMAS["master_artists"]),
        root / "table=master_artists" / "part-00000.parquet",
    )
    (root / "manifest.json").write_text(
        json.dumps({"snapshot_date": SNAPSHOT_DATE, "counts": {"masters": len(master_rows)}})
    )
    return root


def _release(
    release_id: int,
    title: str,
    *,
    released: str | None = None,
    master_id: int | None = None,
    master_is_main_release: bool | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": released,
        "master_id": master_id,
        "master_is_main_release": master_is_main_release,
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
    role_text: str | None = "Performer",
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
    """An artist billed on a release AND credited on its one track.

    Since ADR 0035 an edge means "contributed to the same recording", so a
    release with no tracklist has no edges at all. Every real Discogs release
    has one; the fixtures must too, or they would only ever exercise the
    release-container semantics this project removed.
    """
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


# Standard fixture graph, shared across graph-core tests:
#   R1 "First Light" (master 901, main): Alice(100) + Bob(200)
#   R2 "Second Set" (no master): Bob(200) + Cara(300)
#   R3 "Third Wave" (master 903, main, not in the masters fixture): Cara(300) + Dan(400)
#   R4 "Mega Compilation" (master 904, main): Alice(100) + Eve(500) + PlusOne(501) + PlusTwo(502)
#     -- a 4-linked-artist release, used for the max_artists_per_release cap tests.
#   R5 "Choir Sessions" (no master): Alice(100) + a non-linked "Session Choir" evidence row
#   R6 "Sixth Sense" (master 906, main, not in the masters fixture): Dan(400) + Eve(500)
#   R7 "Compilation Various" (no master): Various(194, excluded) + Frank(600)
#
# With the default cap (50), Alice and Eve connect in 1 hop via R4. With
# max_artists_per_release=3, R4 is excluded from traversal and the only path is
# the 4-hop route R1 -> R2 -> R3 -> R6 (Alice-Bob-Cara-Dan-Eve).
FIXTURE_RELEASES = [
    _release(1, "First Light", released="1993", master_id=901, master_is_main_release=True),
    _release(2, "Second Set", released="1994"),
    _release(3, "Third Wave", released="1995", master_id=903, master_is_main_release=True),
    _release(4, "Mega Compilation", released="1996", master_id=904, master_is_main_release=True),
    _release(5, "Choir Sessions", released="1997"),
    _release(6, "Sixth Sense", released="1998", master_id=906, master_is_main_release=True),
    _release(7, "Compilation Various", released="1999"),
]

FIXTURE_CREDITS = [
    *_performed(1, artist_id=100, name="Alice"),
    *_performed(1, artist_id=200, name="Bob"),
    *_performed(2, artist_id=200, name="Bob"),
    *_performed(2, artist_id=300, name="Cara"),
    *_performed(3, artist_id=300, name="Cara"),
    *_performed(3, artist_id=400, name="Dan"),
    *_performed(4, artist_id=100, name="Alice"),
    *_performed(4, artist_id=500, name="Eve"),
    *_performed(4, artist_id=501, name="PlusOne"),
    *_performed(4, artist_id=502, name="PlusTwo"),
    *_performed(5, artist_id=100, name="Alice"),
    _credit(
        5,
        artist_id=None,
        name="Session Choir",
        scope="release_credit",
        is_linked=False,
        playable_identity=False,
    ),
    *_performed(6, artist_id=400, name="Dan"),
    *_performed(6, artist_id=500, name="Eve"),
    *_performed(7, artist_id=194, name="Various"),
    *_performed(7, artist_id=600, name="Frank"),
]

FIXTURE_MASTERS = [
    {
        "snapshot_date": SNAPSHOT_DATE,
        "master_id": 901,
        "main_release_id": 1,
        "title": "First Light (Deluxe)",
        "year": 1995,
        "genres": [],
        "styles": [],
        "data_quality": None,
        "source_url": "https://example.invalid/master/901",
    }
]


@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    root = tmp_path / "snapshot=20260601"
    return write_synthetic_dataset(root, release_rows=FIXTURE_RELEASES, credit_rows=FIXTURE_CREDITS)


@pytest.fixture
def masters_root(tmp_path: Path) -> Path:
    root = tmp_path / "masters-snapshot=20260601"
    return write_synthetic_masters(root, master_rows=FIXTURE_MASTERS)
