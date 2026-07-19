"""Proxy ranking for album curation: release-variant count x credit richness.

This is the medium-term mechanism for growing the editorial album list
(data/albums/top-albums-v1.json) beyond hand-picked entries -- a signal to
look at, not an automatic ranking. Output is a local-only shortlist; it is
never committed (see data/albums/README.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from .challenge import match_albums
from .graph import CreditGraph, read_parquet_sql


def rank_album_candidates(
    dataset_root: Path,
    *,
    limit: int = 200,
    memory_limit: str = "3GB",
    threads: int = 2,
    release_format_policy: Path | None = None,
) -> list[dict[str, Any]]:
    """Rank master_ids by variant_count * credit_rows, resolved to a real
    {artist, title} query pair via the main release's release_artist credit.

    `release_format_policy`, when given, is a `release-format-scoring-index`
    (see `discogs/release_format_policy.py`) -- candidates whose main release
    isn't in the allow-list never surface at all, so a graph-rich but
    non-studio-album candidate (a compilation, a bootleg) can't be proposed
    for the hybrid catalog in the first place. A candidate whose main
    release has no resolvable release-artist credit is dropped -- there is
    no `{artist, title}` query to hand to `match_albums` without one.
    """
    dataset_root = Path(dataset_root)
    releases_glob = str(dataset_root / "table=releases" / "*.parquet")
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")

    connection = duckdb.connect(database=":memory:")
    connection.execute(f"SET memory_limit = '{memory_limit}'")
    connection.execute(f"SET threads = {int(threads)}")
    connection.execute(f"CREATE VIEW releases AS SELECT * FROM {read_parquet_sql(releases_glob)}")
    connection.execute(f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}")

    policy_filter_sql = ""
    if release_format_policy is not None:
        payload = json.loads(Path(release_format_policy).read_text())
        if payload.get("kind") != "release-format-scoring-index":
            raise ValueError("release_format_policy must be a release-format-scoring-index")
        connection.execute(
            "CREATE TABLE allowed_releases AS "
            "SELECT UNNEST(allowed_release_ids)::BIGINT AS release_id "
            "FROM read_json_auto(?)",
            [str(release_format_policy)],
        )
        policy_filter_sql = "AND v.main_release_id IN (SELECT release_id FROM allowed_releases)"

    rows = connection.execute(
        f"""
        WITH variants AS (
            SELECT master_id, count(*) AS variant_count,
                   min(release_id) FILTER (WHERE master_is_main_release) AS main_release_id
            FROM releases
            WHERE master_id IS NOT NULL
            GROUP BY master_id
        ),
        credit_counts AS (
            SELECT r.master_id, count(*) AS credit_rows
            FROM credits c
            JOIN releases r USING (release_id)
            WHERE r.master_id IS NOT NULL
            GROUP BY r.master_id
        ),
        titles AS (
            SELECT master_id, title
            FROM releases
            WHERE master_is_main_release
            QUALIFY row_number() OVER (PARTITION BY master_id ORDER BY release_id) = 1
        ),
        release_artists AS (
            SELECT release_id, artist_id, name
            FROM credits
            WHERE credit_scope = 'release_artist' AND playable_identity AND artist_id IS NOT NULL
            QUALIFY row_number() OVER (PARTITION BY release_id ORDER BY artist_id) = 1
        )
        SELECT v.master_id, t.title AS sample_title, v.variant_count,
               coalesce(cc.credit_rows, 0) AS credit_rows,
               v.variant_count * coalesce(cc.credit_rows, 0) AS score,
               v.main_release_id, ra.artist_id, ra.name AS artist_name
        FROM variants v
        LEFT JOIN credit_counts cc USING (master_id)
        LEFT JOIN titles t USING (master_id)
        LEFT JOIN release_artists ra ON ra.release_id = v.main_release_id
        WHERE ra.artist_id IS NOT NULL
        {policy_filter_sql}
        ORDER BY score DESC, v.master_id
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    connection.close()
    return [
        {
            "master_id": int(row[0]),
            "sample_title": row[1],
            "variant_count": int(row[2]),
            "credit_rows": int(row[3]),
            "score": int(row[4]),
            "main_release_id": int(row[5]),
            "artist_id": int(row[6]),
            "artist_name": row[7],
        }
        for row in rows
    ]


def assemble_album_catalog(
    graph: CreditGraph,
    editorial_albums: list[dict[str, str]],
    candidates: list[dict[str, Any]],
    *,
    target_count: int,
    private_weight_fn: Callable[[int], float] | None = None,
    allowed_release_ids: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Combine the editorial backbone with graph-rich candidates up to
    `target_count` (see ADR 0037). Deterministic given a fixed graph
    snapshot, editorial list, candidate list, and weighting function.

    The editorial list always wins: every editorial entry is kept exactly as
    given, and any candidate whose artist_id matches an already-matched
    editorial artist is dropped rather than duplicated. Remaining candidates
    are ranked by `score` (optionally nudged by `private_weight_fn`, a
    local-only hook -- see ADR 0037/docs/PUBLIC_PRIVATE_BOUNDARY.md; never
    published, and this function never records which albums it affected) and
    added in that order until `target_count` is reached or candidates run
    out. Never pads past what real candidates support.

    `allowed_release_ids`, when given, fail-closed gates the *editorial* side
    by the same studio-album-v1 policy `candidates` was already filtered by
    upstream in `rank_album_candidates` -- an editorial entry whose matched
    release isn't in the allow-list is dropped, never silently included, and
    never fabricated back in from the candidate pool.
    """
    if target_count <= 0:
        raise ValueError("target_count must be positive")

    matched_editorial, missed_editorial = match_albums(
        graph, editorial_albums, allowed_release_ids=allowed_release_ids
    )
    editorial_artist_ids = {m.artist_id for m in matched_editorial}
    # match_albums reports misses as the original query dicts, so anything
    # not in that list succeeded -- used to keep only real, matching editorial
    # entries in the generated catalog (an entry that misses the snapshot or
    # fails the format gate would just miss again downstream; no reason to
    # carry it forward and double-report the same gap).
    matched_editorial_queries = [a for a in editorial_albums if a not in missed_editorial]

    def _weighted_score(candidate: dict[str, Any]) -> float:
        base = float(candidate["score"])
        if private_weight_fn is None:
            return base
        return base * (1.0 + private_weight_fn(int(candidate["artist_id"])))

    eligible_candidates = [c for c in candidates if c["artist_id"] not in editorial_artist_ids]
    ranked_candidates = sorted(
        eligible_candidates, key=lambda c: (-_weighted_score(c), c["master_id"])
    )

    # Sized against matched_editorial (real matches), not len(editorial_albums)
    # (the raw query count) -- an editorial entry that misses the snapshot
    # shouldn't silently shrink how many candidates fill out the target.
    remaining_slots = max(0, target_count - len(matched_editorial))
    added_candidate_ids: set[int] = set()
    candidate_albums: list[dict[str, str]] = []
    for candidate in ranked_candidates:
        if len(candidate_albums) >= remaining_slots:
            break
        artist_id = int(candidate["artist_id"])
        if artist_id in added_candidate_ids:
            continue
        added_candidate_ids.add(artist_id)
        candidate_albums.append(
            {"artist": candidate["artist_name"], "title": candidate["sample_title"]}
        )

    return {
        "version": 1,
        "source_note": (
            "Hybrid catalog: an editorial backbone plus graph-rich additions selected by "
            "deterministic candidate scoring (ADR 0037). Not itself committed -- combined "
            "at build time from data/albums/top-albums-v1.json and a rank-album-candidates "
            "shortlist."
        ),
        "target_count": target_count,
        "editorial_count": len(matched_editorial_queries),
        "editorial_missed": missed_editorial,
        "candidate_count_considered": len(candidates),
        "candidate_count_added": len(candidate_albums),
        "albums": [*matched_editorial_queries, *candidate_albums],
    }
