import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from networked_players_catalog.discogs.dataset_locator import (
    DatasetLocatorError,
    dataset_file_urls,
    resolve_dataset,
)
from networked_players_catalog.discogs.parquet import write_release_dataset
from networked_players_catalog.discogs.releases import iter_releases

FIXTURE = Path(__file__).parent / "fixtures" / "releases.xml"
SNAPSHOT = "20260501"


@pytest.fixture
def served_dataset(tmp_path: Path) -> Iterator[str]:
    """A synthetic dataset served by a real (loopback-only) HTTP server."""

    source_url = "https://example.test/discogs_20260501_releases.xml.gz"
    records = iter_releases(FIXTURE, snapshot_date=SNAPSHOT, source_url=source_url)
    write_release_dataset(
        records, tmp_path, snapshot_date=SNAPSHOT, source_url=source_url, chunk_releases=1
    )

    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_port
        yield f"http://{host}:{port}/snapshot={SNAPSHOT}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_locates_table_files_with_integrity_metadata(served_dataset: str) -> None:
    files = dataset_file_urls(served_dataset, table="releases")
    # chunk_releases=1 over the 2-release fixture -> two release part files.
    assert [f.path for f in files] == [
        "table=releases/part-00000.parquet",
        "table=releases/part-00001.parquet",
    ]
    for item in files:
        assert item.url == f"{served_dataset}/{item.path}"
        assert item.size_bytes > 0
        assert len(item.sha256) == 64
        assert item.rows == 1


def test_urls_are_actually_fetchable_and_hash_verified(served_dataset: str) -> None:
    import hashlib
    from urllib.request import urlopen

    (first, *_) = dataset_file_urls(served_dataset, table="credits")
    with urlopen(first.url, timeout=30) as response:
        payload = response.read()
    assert len(payload) == first.size_bytes
    assert hashlib.sha256(payload).hexdigest() == first.sha256


def test_unknown_table_raises(served_dataset: str) -> None:
    with pytest.raises(DatasetLocatorError, match="no files for table"):
        dataset_file_urls(served_dataset, table="nonexistent")


def test_unreachable_server_raises() -> None:
    with pytest.raises(DatasetLocatorError, match="could not fetch"):
        dataset_file_urls("http://127.0.0.1:1/snapshot=20260501", table="releases")


@pytest.fixture
def served_catalog_data_root(tmp_path: Path) -> Iterator[str]:
    """Serves <tmp>/discogs/snapshot=SNAPSHOT/ at the root URL, matching the
    <CATALOG_DATA_URL>/<dataset>/snapshot=<X> layout resolve_dataset expects."""

    source_url = "https://example.test/discogs_20260501_releases.xml.gz"
    records = iter_releases(FIXTURE, snapshot_date=SNAPSHOT, source_url=source_url)
    write_release_dataset(
        records,
        tmp_path / "discogs",
        snapshot_date=SNAPSHOT,
        source_url=source_url,
        chunk_releases=1,
    )

    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_port
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_resolve_dataset_prefers_verified_local_cache(
    served_catalog_data_root: str, tmp_path: Path
) -> None:
    from networked_players_catalog.discogs.dataset_fetch import fetch_dataset

    cache_root = tmp_path / "cache"
    fetch_dataset(
        f"{served_catalog_data_root}/discogs/snapshot={SNAPSHOT}",
        cache_root / "discogs" / f"snapshot={SNAPSHOT}",
    )

    source = resolve_dataset(
        "discogs",
        SNAPSHOT,
        env={"CATALOG_DATA_DIR": str(cache_root), "CATALOG_DATA_URL": "http://127.0.0.1:1"},
    )
    assert source.kind == "local"
    assert source.base == str(cache_root / "discogs" / f"snapshot={SNAPSHOT}")


def test_resolve_dataset_skips_unverified_local_cache_and_falls_back_to_http(
    served_catalog_data_root: str, tmp_path: Path
) -> None:
    unverified_root = tmp_path / "cache" / "discogs" / f"snapshot={SNAPSHOT}"
    unverified_root.mkdir(parents=True)
    (unverified_root / "manifest.json").write_text("{}")  # no .verified.json marker

    source = resolve_dataset(
        "discogs",
        SNAPSHOT,
        env={
            "CATALOG_DATA_DIR": str(tmp_path / "cache"),
            "CATALOG_DATA_URL": served_catalog_data_root,
        },
    )
    assert source.kind == "http"


def test_resolve_dataset_uses_http_only(served_catalog_data_root: str) -> None:
    source = resolve_dataset(
        "discogs", SNAPSHOT, env={"CATALOG_DATA_URL": served_catalog_data_root}
    )
    assert source.kind == "http"
    assert source.base == f"{served_catalog_data_root}/discogs/snapshot={SNAPSHOT}"


def test_resolve_dataset_raises_when_neither_env_var_resolves() -> None:
    with pytest.raises(DatasetLocatorError, match="could not resolve"):
        resolve_dataset("discogs", SNAPSHOT, env={})
