"""Both candidate-report commands must refuse to write outside `local/`.

`review-album-candidates` reads the private, collection-seeded one-hop corpus,
so its per-candidate detail (titles, master ids, per-album counts) is
collection-membership-adjacent under `docs/PUBLIC_PRIVATE_BOUNDARY.md`'s own
checklist. Its `--help` promised "local-only output" from the start; until
Phase 7's preflight nothing enforced it, while its sibling
`rank-exploration-tier` already did. These tests pin both, and deliberately
assert the guard fires *before* any dataset is opened -- a report that is
built and then rejected has already spent the work, and a partial write is
exactly what an atomic guard exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_catalog.cli import main


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.parametrize(
    "output_name",
    [
        "apps/web/public/data/catalog/albums.v1.json",
        "data/albums/top-albums-v1.json",
        "docs/data/leaked.json",
        "report.json",
    ],
)
def test_review_album_candidates_refuses_to_write_outside_local(
    tmp_path: Path, output_name: str
) -> None:
    candidates = _write(tmp_path / "candidates.json", [])
    graph = _write(tmp_path / "graph.v2.json", {"node_ids": [1, 2, 3]})
    output = tmp_path / output_name

    with pytest.raises(ValueError, match="refuses to write outside local/"):
        main(
            [
                "review-album-candidates",
                "--dataset",
                str(tmp_path / "does-not-exist"),
                "--candidates",
                str(candidates),
                "--pathfinding-graph",
                str(graph),
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


def test_review_album_candidates_accepts_a_local_path(tmp_path: Path) -> None:
    """The guard must not be so broad it blocks the real, documented path.

    `local/` anywhere in the path is enough -- the operator runbook uses a
    repo-relative `local/research/...` and an absolute path under a checkout
    must work identically."""
    candidates = _write(tmp_path / "candidates.json", [])
    graph = _write(tmp_path / "graph.v2.json", {"node_ids": [1]})
    output = tmp_path / "local" / "research" / "catalog-expansion" / "review.json"

    # Gets past the guard, then fails on the missing dataset -- which is the
    # proof it got past the guard.
    with pytest.raises(Exception) as excinfo:
        main(
            [
                "review-album-candidates",
                "--dataset",
                str(tmp_path / "does-not-exist"),
                "--candidates",
                str(candidates),
                "--pathfinding-graph",
                str(graph),
                "--output",
                str(output),
            ]
        )
    assert "refuses to write outside local/" not in str(excinfo.value)
