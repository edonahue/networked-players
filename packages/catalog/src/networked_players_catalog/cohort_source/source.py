"""Provenance for one saved cohort source. See data/contracts/cohort-source-v1.md
and docs/decisions/0028-curated-cohort-source-ingestion.md.

The raw saved HTML itself is never held here -- only a pointer (a bare
filename, never an absolute path) and a sha256 for integrity/dedup. It lives
under the git-ignored data/private/source-html/ and is never committed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

COHORT_SOURCE_VERSION = 1


@dataclass(slots=True)
class CohortSourceMeta:
    """Provenance for one saved cohort source page."""

    cohort_source_version: int
    source_url: str
    page_title: str
    saved_at: str
    operator_note: str = ""
    raw_html_sha256: str | None = None
    raw_html_relpath: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def read(cls, path: Path) -> CohortSourceMeta:
        payload = json.loads(path.read_text())
        return cls(**payload)


def build_cohort_source_meta(
    *,
    source_url: str,
    page_title: str,
    saved_at: str,
    operator_note: str = "",
    raw_html_path: Path | None = None,
) -> CohortSourceMeta:
    """Build a `CohortSourceMeta`, computing the raw-HTML pointer if given a path.

    Only the file's own name is kept (`raw_html_relpath`) -- never its parent
    directories -- so no absolute or local filesystem path can end up in an
    artifact derived from this metadata.
    """
    raw_html_sha256 = None
    raw_html_relpath = None
    if raw_html_path is not None:
        raw_html_sha256 = hashlib.sha256(raw_html_path.read_bytes()).hexdigest()
        raw_html_relpath = raw_html_path.name

    return CohortSourceMeta(
        cohort_source_version=COHORT_SOURCE_VERSION,
        source_url=source_url,
        page_title=page_title,
        saved_at=saved_at,
        operator_note=operator_note,
        raw_html_sha256=raw_html_sha256,
        raw_html_relpath=raw_html_relpath,
    )
