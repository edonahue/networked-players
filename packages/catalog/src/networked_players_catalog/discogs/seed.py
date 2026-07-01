"""Reduce a local Discogs collection export to a release-ID-only private seed.

Reads exactly one column (`release_id`) from a source CSV export and never
accesses any other field -- this is structural, not a post-hoc filter. See
data/contracts/discogs-seed-v1.md and ADR 0011.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEED_VERSION = 1
REQUIRED_COLUMN = "release_id"


class SeedImportError(RuntimeError):
    """Raised when a collection export cannot be safely reduced to a release-ID seed."""


@dataclass(slots=True)
class SeedManifest:
    """A private, never-published, release-ID-only seed."""

    seed_version: int
    source: str
    imported_at: str
    release_ids: list[int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def read(cls, path: Path) -> SeedManifest:
        payload = json.loads(path.read_text())
        return cls(**payload)


def import_seed_csv(
    csv_path: Path, *, source: str = "discogs-collection-export-csv"
) -> SeedManifest:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or REQUIRED_COLUMN not in reader.fieldnames:
            raise SeedImportError(f"export is missing a {REQUIRED_COLUMN!r} column")

        release_ids: set[int] = set()
        for row_number, row in enumerate(reader, start=2):  # header is row 1
            raw_value = (row.get(REQUIRED_COLUMN) or "").strip()
            if not raw_value:
                continue
            try:
                release_ids.add(int(raw_value))
            except ValueError as exc:
                raise SeedImportError(
                    f"row {row_number}: {REQUIRED_COLUMN!r} value {raw_value!r} is not an integer"
                ) from exc

    if not release_ids:
        raise SeedImportError("no valid release IDs found in export")

    return SeedManifest(
        seed_version=SEED_VERSION,
        source=source,
        imported_at=datetime.now(UTC).isoformat(),
        release_ids=sorted(release_ids),
    )
