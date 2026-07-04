"""Locate a served dataset's parquet files from its own manifest.

The catalog-data HTTP layer (`infra/swarm/docker-compose.catalog-data.yml`,
ADR 0024) serves the processed dataset tree read-only. HTTP has no native
globbing, but every dataset in this project already ships a
``manifest.json`` listing the exact relative path, size, and sha256 of each
parquet file -- so clients build precise URL lists from the manifest instead
of guessing, and get integrity metadata for free.

Typical use from a remote Dask worker or a notebook::

    files = dataset_file_urls("http://<coordination-lan-ip>:8791/discogs-onehop/snapshot=20260601",
                              table="credits")
    ddf = dd.read_parquet([f.url for f in files])

Stdlib-only on purpose: this module runs inside lean worker venvs that
deliberately exclude heavy dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.request import urlopen


class DatasetLocatorError(RuntimeError):
    """Raised when a served dataset's manifest can't be read or understood."""


@dataclass(frozen=True, slots=True)
class DatasetFile:
    """One parquet file of a served dataset, as the manifest describes it."""

    url: str
    path: str
    size_bytes: int
    sha256: str
    rows: int


def dataset_file_urls(
    dataset_base_url: str, *, table: str, timeout_seconds: float = 30.0
) -> list[DatasetFile]:
    """Fetch ``<dataset_base_url>/manifest.json`` and return the files of one table.

    ``dataset_base_url`` points at a dataset root (the directory containing
    ``manifest.json``), e.g. ``http://host:8791/discogs-onehop/snapshot=20260601``.
    """

    base = dataset_base_url.rstrip("/")
    manifest_url = f"{base}/manifest.json"
    try:
        with urlopen(manifest_url, timeout=timeout_seconds) as response:
            manifest = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise DatasetLocatorError(f"could not fetch {manifest_url}: {exc}") from exc

    files = manifest.get("files")
    if not isinstance(files, list):
        raise DatasetLocatorError(f"{manifest_url} has no usable 'files' list")

    prefix = f"table={table}/"
    selected: list[DatasetFile] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise DatasetLocatorError(f"{manifest_url} has a malformed files entry: {entry!r}")
        path = str(entry.get("path", ""))
        if not path.startswith(prefix):
            continue
        selected.append(
            DatasetFile(
                url=f"{base}/{path}",
                path=path,
                size_bytes=int(entry["size_bytes"]),
                sha256=str(entry["sha256"]),
                rows=int(entry["rows"]),
            )
        )
    if not selected:
        raise DatasetLocatorError(
            f"{manifest_url} lists no files for table={table!r} -- "
            "check the table name against the dataset's contract"
        )
    return sorted(selected, key=lambda item: item.path)
