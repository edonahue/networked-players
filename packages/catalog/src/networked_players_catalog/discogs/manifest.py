"""Versioned manifests for Discogs monthly data-dump objects."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import quote

# Discogs moved public dump hosting off the raw S3 bucket path behind a Cloudflare
# proxy at data.discogs.com; the old direct-path scheme now returns a bucket-level
# AccessDenied (confirmed 2026-07-01, not network- or snapshot-specific). The new
# host serves objects via a query-string download endpoint, not a literal path.
DEFAULT_BASE_URL = "https://data.discogs.com"
SNAPSHOT_RE = re.compile(r"^\d{8}$")


class DumpKind(StrEnum):
    """The four object types published in a monthly Discogs dump."""

    ARTISTS = "artists"
    LABELS = "labels"
    MASTERS = "masters"
    RELEASES = "releases"


@dataclass(slots=True)
class DumpObject:
    """Expected and observed metadata for one compressed XML object."""

    kind: str
    url: str
    filename: str
    size_bytes: int | None = None
    etag: str | None = None
    sha256: str | None = None
    downloaded_at: str | None = None


@dataclass(slots=True)
class SnapshotManifest:
    """Manifest for a coherent monthly snapshot."""

    manifest_version: int
    source: str
    snapshot_date: str
    terms_reviewed_at: str
    objects: list[DumpObject]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def read(cls, path: Path) -> SnapshotManifest:
        payload = json.loads(path.read_text())
        payload["objects"] = [DumpObject(**item) for item in payload["objects"]]
        return cls(**payload)

    def object_for(self, kind: DumpKind) -> DumpObject:
        for item in self.objects:
            if item.kind == kind.value:
                return item
        raise KeyError(f"Manifest does not include {kind.value!r}")


def validate_snapshot_date(snapshot_date: str) -> None:
    if not SNAPSHOT_RE.fullmatch(snapshot_date):
        raise ValueError("snapshot date must use YYYYMMDD")
    if snapshot_date[6:] != "01":
        raise ValueError(
            "Discogs monthly snapshot dates are expected to use the first day of a month"
        )


def dump_filename(snapshot_date: str, kind: DumpKind) -> str:
    return f"discogs_{snapshot_date}_{kind.value}.xml.gz"


def object_url(snapshot_date: str, kind: DumpKind, base_url: str = DEFAULT_BASE_URL) -> str:
    validate_snapshot_date(snapshot_date)
    key = f"data/{snapshot_date[:4]}/{dump_filename(snapshot_date, kind)}"
    return f"{base_url.rstrip('/')}/?download={quote(key, safe='')}"


def build_manifest(
    snapshot_date: str,
    terms_reviewed_at: str,
    base_url: str = DEFAULT_BASE_URL,
) -> SnapshotManifest:
    """Build an offline manifest from the documented monthly naming convention.

    Creating a manifest does not claim that the objects are reachable. The downloader records
    observed size and checksum metadata only after a successful transfer.
    """

    validate_snapshot_date(snapshot_date)
    objects = []
    for kind in DumpKind:
        url = object_url(snapshot_date, kind, base_url)
        filename = dump_filename(snapshot_date, kind)
        objects.append(DumpObject(kind=kind.value, url=url, filename=filename))
    return SnapshotManifest(
        manifest_version=1,
        source="Discogs monthly data dumps",
        snapshot_date=snapshot_date,
        terms_reviewed_at=terms_reviewed_at,
        objects=objects,
    )
