from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from networked_players_catalog.cli import main
from networked_players_catalog.discogs.dataset_fetch import (
    FetchError,
    fetch_dataset,
    verify_dataset,
)


def _write_source_dataset(root: Path, contents: dict[str, bytes]) -> None:
    files = []
    for rel_path, data in contents.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files.append(
            {
                "path": rel_path,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "rows": 1,
            }
        )
    (root / "manifest.json").write_text(json.dumps({"snapshot_date": "20260601", "files": files}))


@pytest.fixture
def served_dataset(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_source_dataset(
        source_root,
        {
            "table=releases/part-00000.parquet": b"release-bytes",
            "table=credits/part-00000.parquet": b"credit-bytes-longer",
        },
    )

    handler = partial(SimpleHTTPRequestHandler, directory=str(source_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_port
        yield f"http://{host}:{port}", source_root
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fetch_dataset_happy_path(served_dataset: tuple[str, Path], tmp_path: Path) -> None:
    base_url, _ = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"

    result = fetch_dataset(base_url, dest)

    assert result["status"] == "fetched"
    assert result["files_downloaded"] == 2
    assert result["files_reused"] == 0
    assert (dest / "manifest.json").exists()
    assert (dest / ".verified.json").exists()
    assert (dest / "table=releases" / "part-00000.parquet").read_bytes() == b"release-bytes"


def test_fetch_dataset_rejects_tampered_served_file(
    served_dataset: tuple[str, Path], tmp_path: Path
) -> None:
    base_url, source_root = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"

    # Corrupt the served bytes without updating the manifest's sha256.
    (source_root / "table=releases" / "part-00000.parquet").write_bytes(b"tampered!!")

    with pytest.raises(FetchError, match="expected"):
        fetch_dataset(base_url, dest)
    assert not dest.exists()


def test_fetch_dataset_is_idempotent_on_rerun(
    served_dataset: tuple[str, Path], tmp_path: Path
) -> None:
    base_url, _ = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"

    first = fetch_dataset(base_url, dest)
    assert first["status"] == "fetched"

    # A garbage base_url proves the second call never touches the network --
    # the already-valid dest short-circuits before any manifest fetch.
    second = fetch_dataset("http://127.0.0.1:1", dest)
    assert second["status"] == "already-valid"


def test_fetch_dataset_resumes_from_a_matching_staged_file(
    served_dataset: tuple[str, Path], tmp_path: Path
) -> None:
    base_url, source_root = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"

    # Pre-stage one correct file, simulating a prior interrupted run.
    staging = dest.parent / f".{dest.name}.partial"
    staged_file = staging / "table=releases" / "part-00000.parquet"
    staged_file.parent.mkdir(parents=True)
    staged_file.write_bytes((source_root / "table=releases" / "part-00000.parquet").read_bytes())

    result = fetch_dataset(base_url, dest)

    assert result["files_reused"] == 1
    assert result["files_downloaded"] == 1


def test_fetch_dataset_refuses_over_max_total_bytes(
    served_dataset: tuple[str, Path], tmp_path: Path
) -> None:
    base_url, _ = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"

    with pytest.raises(FetchError, match="exceeding"):
        fetch_dataset(base_url, dest, max_total_bytes=5)
    assert not dest.exists()
    assert not (dest.parent / f".{dest.name}.partial").exists()


def test_fetch_dataset_refuses_without_headroom(
    served_dataset: tuple[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_url, _ = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"

    import shutil as shutil_module

    class _FakeUsage:
        free = 1

    monkeypatch.setattr(shutil_module, "disk_usage", lambda _path: _FakeUsage())

    with pytest.raises(FetchError, match="insufficient free space"):
        fetch_dataset(base_url, dest, headroom_bytes=1_000_000_000)


def test_fetch_dataset_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "manifest.json").write_text(
        json.dumps({"files": [{"path": "../evil", "size_bytes": 1, "sha256": "x", "rows": 1}]})
    )
    handler = partial(SimpleHTTPRequestHandler, directory=str(source_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_port
        with pytest.raises(FetchError, match="unsafe file path"):
            fetch_dataset(f"http://{host}:{port}", tmp_path / "dest")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_verify_dataset_passes_on_a_clean_fetch(
    served_dataset: tuple[str, Path], tmp_path: Path
) -> None:
    base_url, _ = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"
    fetch_dataset(base_url, dest)

    result = verify_dataset(dest)
    assert result["status"] == "verified"
    assert result["files_verified"] == 2


def test_verify_dataset_fails_on_local_tampering(
    served_dataset: tuple[str, Path], tmp_path: Path
) -> None:
    base_url, _ = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"
    fetch_dataset(base_url, dest)

    (dest / "table=credits" / "part-00000.parquet").write_bytes(b"corrupted-locally")

    with pytest.raises(FetchError, match="verification failed"):
        verify_dataset(dest)


def test_fetch_dataset_cli_wiring(served_dataset: tuple[str, Path], tmp_path: Path, capsys) -> None:
    base_url, _ = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"

    exit_code = main(["fetch-dataset", "--base-url", base_url, "--dest", str(dest)])
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "fetched"


def test_verify_dataset_cli_wiring(
    served_dataset: tuple[str, Path], tmp_path: Path, capsys
) -> None:
    base_url, _ = served_dataset
    dest = tmp_path / "cache" / "discogs" / "snapshot=20260601"
    fetch_dataset(base_url, dest)
    capsys.readouterr()

    exit_code = main(["verify-dataset", "--dest", str(dest)])
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "verified"
