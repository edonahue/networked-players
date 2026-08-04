"""Analysis primitives run against a built topic corpus.

Slice A ships one real, working analysis (`personnel_timeline`) to prove
the request -> corpus -> analysis -> report -> findings pipeline end to
end. The remaining five names in `request.ANALYSIS_NAMES`
(`role_distribution`, `contributor_network`, `community_detection`,
`bridge_analysis`, `temporal_comparison`) are Slice D's job, built once
Slice C's graph-library benchmark has picked the primitives they need --
`ANALYSIS_REGISTRY` only ever contains analyses that are actually
implemented, so a request naming one that isn't yet built is skipped and
recorded as skipped, never silently treated as having run.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb


def personnel_timeline(corpus_snapshot_root: Path) -> dict[str, Any]:
    """Album x contributor personnel matrix: for every retained release,
    every playable credited artist (deduped by artist_id/name/role_text),
    ordered chronologically. A direct query over the corpus's own
    releases/credits tables -- no separate graph construction needed for
    this view."""
    releases_glob = str(corpus_snapshot_root / "table=releases" / "*.parquet")
    credits_glob = str(corpus_snapshot_root / "table=credits" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        rows = connection.execute(
            f"""
            SELECT
                r.release_id,
                r.title,
                r.released,
                list(DISTINCT
                    {{'artist_id': c.artist_id, 'name': c.name, 'role_text': c.role_text}}
                ) AS contributors
            FROM read_parquet('{releases_glob}', hive_partitioning=false) r
            JOIN read_parquet('{credits_glob}', hive_partitioning=false) c
              ON c.release_id = r.release_id
            WHERE c.playable_identity
            GROUP BY r.release_id, r.title, r.released
            ORDER BY r.released, r.title
            """
        ).fetchall()
    finally:
        connection.close()

    albums = [
        {
            "release_id": int(release_id),
            "title": title,
            "released": released,
            "contributors": contributors,
        }
        for release_id, title, released, contributors in rows
    ]
    return {"kind": "personnel_timeline", "albums": albums}


ANALYSIS_REGISTRY: dict[str, Callable[[Path], dict[str, Any]]] = {
    "personnel_timeline": personnel_timeline,
}
