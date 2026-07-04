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
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True, slots=True)
class DatasetSource:
    """Where a job should read one dataset/snapshot from, per resolve_dataset."""

    kind: str  # "local" or "http"
    base: str  # a local directory path, or an HTTP dataset root URL


def resolve_dataset(
    dataset: str,
    snapshot: str,
    *,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> DatasetSource:
    """Pick a data source per ADR 0025's resolution order.

    1. A validated local cache (``CATALOG_DATA_DIR``) -- a dataset directory
       containing both ``manifest.json`` and a ``.verified.json`` marker
       (written by ``dataset_fetch.fetch_dataset``/``verify_dataset``). An
       unverified cache is never preferred over a fresh HTTP read.
    2. The catalog-data HTTP layer (``CATALOG_DATA_URL``, ADR 0024).
    3. Otherwise, raise -- naming both env vars and what was checked, so a
       job fails loudly instead of silently reading nothing.
    """
    env = os.environ if env is None else env
    checked: list[str] = []

    data_dir = env.get("CATALOG_DATA_DIR")
    if data_dir:
        local_root = Path(data_dir) / dataset / f"snapshot={snapshot}"
        if (local_root / "manifest.json").exists() and (local_root / ".verified.json").exists():
            return DatasetSource(kind="local", base=str(local_root))
        checked.append(f"CATALOG_DATA_DIR={data_dir} (no validated cache at {local_root})")

    data_url = env.get("CATALOG_DATA_URL")
    if data_url:
        base = f"{data_url.rstrip('/')}/{dataset}/snapshot={snapshot}"
        try:
            with urlopen(f"{base}/manifest.json", timeout=timeout_seconds):
                pass
            return DatasetSource(kind="http", base=base)
        except OSError as exc:
            checked.append(f"CATALOG_DATA_URL={data_url} (fetch failed: {exc})")

    if not checked:
        checked.append("neither CATALOG_DATA_DIR nor CATALOG_DATA_URL is set")
    raise DatasetLocatorError(
        f"could not resolve {dataset}/snapshot={snapshot}: " + "; ".join(checked)
    )
