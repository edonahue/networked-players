"""Analysis primitives run against a built topic corpus.

Slice A shipped `personnel_timeline` to prove the request -> corpus ->
analysis -> report -> findings pipeline end to end. Slice D adds the
remaining five: `role_distribution` (below, reusing Phase 2's
`role_taxonomy.RoleCategory` directly), `temporal_comparison` (below, a
DuckDB aggregation), and `contributor_network`/`community_detection`/
`bridge_analysis` (`graph_analysis.py`, built on ADR 0055's selected
igraph). `ANALYSIS_REGISTRY` only ever contains analyses that are
actually implemented, so a request naming one that isn't yet built is
skipped and recorded as skipped, never silently treated as having run.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from networked_players_graph_core.role_taxonomy import classify_role


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


def _release_year(released: str | None) -> str | None:
    if not released or len(released) < 4 or not released[:4].isdigit():
        return None
    return released[:4]


def role_distribution(corpus_snapshot_root: Path) -> dict[str, Any]:
    """Role-category distribution over the corpus's real credits, reusing
    `role_taxonomy.RoleCategory`/`classify_role` directly (Phase 2 Slice
    B) -- a real reuse, not a re-derivation of the taxonomy. Grouped by
    release year, so "how did the role mix change over time" is a direct
    read of the output rather than a separate computation."""
    credits_glob = str(corpus_snapshot_root / "table=credits" / "*.parquet")
    releases_glob = str(corpus_snapshot_root / "table=releases" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        rows = connection.execute(
            f"""
            SELECT r.released, c.role_text
            FROM read_parquet('{credits_glob}', hive_partitioning=false) c
            JOIN read_parquet('{releases_glob}', hive_partitioning=false) r
              ON r.release_id = c.release_id
            WHERE c.playable_identity
            """
        ).fetchall()
    finally:
        connection.close()

    overall: Counter[str] = Counter()
    by_year: dict[str, Counter[str]] = defaultdict(Counter)
    for released, role_text in rows:
        year = _release_year(released)
        for category in classify_role(role_text):
            overall[category.value] += 1
            if year is not None:
                by_year[year][category.value] += 1

    return {
        "kind": "role_distribution",
        "overall": dict(sorted(overall.items())),
        "by_year": {year: dict(sorted(counts.items())) for year, counts in sorted(by_year.items())},
    }


def temporal_comparison(corpus_snapshot_root: Path) -> dict[str, Any]:
    """Era boundaries derived from measured personnel-turnover discontinuities
    between consecutive release years, never pre-assumed dates -- per year
    (ordered chronologically), the Jaccard similarity of that year's playable
    contributor set against the previous year's is computed; a year whose
    similarity falls below `turnover_threshold` is flagged as a measured
    turnover point, and the resulting contiguous runs between turnover points
    are reported as candidate eras (labeled only by their real start/end
    years -- never a descriptive name, which stays a human/interpretation
    step, see ADR 0054)."""
    credits_glob = str(corpus_snapshot_root / "table=credits" / "*.parquet")
    releases_glob = str(corpus_snapshot_root / "table=releases" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        rows = connection.execute(
            f"""
            SELECT r.released, c.artist_id
            FROM read_parquet('{credits_glob}', hive_partitioning=false) c
            JOIN read_parquet('{releases_glob}', hive_partitioning=false) r
              ON r.release_id = c.release_id
            WHERE c.playable_identity
            """
        ).fetchall()
    finally:
        connection.close()

    contributors_by_year: dict[str, set[int]] = defaultdict(set)
    for released, artist_id in rows:
        year = _release_year(released)
        if year is not None:
            contributors_by_year[year].add(int(artist_id))

    years = sorted(contributors_by_year)
    turnover_threshold = 0.2
    year_similarity: list[dict[str, Any]] = []
    turnover_years: list[str] = []
    for previous_year, year in itertools.pairwise(years):
        previous_set = contributors_by_year[previous_year]
        current_set = contributors_by_year[year]
        union = previous_set | current_set
        jaccard = len(previous_set & current_set) / len(union) if union else 0.0
        year_similarity.append(
            {"year": year, "previous_year": previous_year, "contributor_overlap_jaccard": jaccard}
        )
        if jaccard < turnover_threshold:
            turnover_years.append(year)

    eras: list[dict[str, Any]] = []
    if years:
        era_start = years[0]
        for year in years[1:]:
            if year in turnover_years:
                eras.append({"start_year": era_start, "end_year_exclusive": year})
                era_start = year
        eras.append({"start_year": era_start, "end_year_exclusive": None})

    return {
        "kind": "temporal_comparison",
        "turnover_threshold": turnover_threshold,
        "year_similarity": year_similarity,
        "turnover_years": turnover_years,
        "eras": eras,
    }


ANALYSIS_REGISTRY: dict[str, Callable[[Path], dict[str, Any]]] = {
    "personnel_timeline": personnel_timeline,
    "role_distribution": role_distribution,
    "temporal_comparison": temporal_comparison,
}

# contributor_network/community_detection/bridge_analysis need igraph
# (packages/research's optional "graph" extra, ADR 0055) -- registered only
# when it's actually importable, so a base install (no graph extra) still
# runs every other analysis; a request naming one of these three without
# the extra installed is skipped and reported as skipped, same as any
# not-yet-implemented analysis, never a hard failure.
try:
    from .graph_analysis import bridge_analysis, community_detection, contributor_network

    ANALYSIS_REGISTRY["contributor_network"] = contributor_network
    ANALYSIS_REGISTRY["community_detection"] = community_detection
    ANALYSIS_REGISTRY["bridge_analysis"] = bridge_analysis
except ImportError:
    pass
