"""Build a candidate pool by RELATIONSHIP to the published catalog, not by
popularity (graph-expansion Phase 2, the plan's "Pool B" in section 2 finding 3
and section 5.2's inputs; corrected supply stage in section 21.3 slice X2).

A master enters this pool when at least `minimum_overlap` performers already on
published catalog albums have a performer-qualifying credit on one of its
releases -- so "this candidate connects to what we already have" is true by
CONSTRUCTION, not something a downstream scorer has to hope for.

Why this exists, measured rather than assumed. Round 1 (2026-09-04) used
`rank_album_candidates` as its pool source, which ranks by
`variant_count * credit_rows` -- corpus weight, with no notion of the catalog
at all beyond a `NOT IN` exclusion (its own docstring: "a proxy ranking… a
signal to look at, not an automatic ranking"). Two consequences showed up in
the real run:

- At `--limit 200`, **every** in-band candidate scored `new_performers = 0` and
  Reggae had exactly one candidate in the whole pool. The graph-value and
  coverage lanes had nothing to work with.
- The one-hop corpus retains a release when ONE frontier artist has a performer
  credit on it, but `credit_rows` counts EVERY credit row on that release -- so
  a heavily-reissued blockbuster retained through a single session player
  outscores records genuinely tied to the catalog.

The performer gate here is `credit_edges_sql`'s own ADR 0068 rule, expressed in
SQL the same way `graph.py` expresses it (`_edge_ineligible_role_sql` plus
billing-scope-or-`is_performer_role_sql`) -- never a second, looser copy. That
matters for agreement: `score_expansion_candidates`' `roster_size` and
`overlap_existing` judge a candidate by
`pathfinding_graph.edge_eligible_membership_artist_ids`, the Python mirror of
this same rule, so the pool and the score cannot disagree about who counts as a
performer.

Aggregation happens in DuckDB, not Python: the alternative
(`CreditGraph.credit_rows_for_artists` over several thousand catalog
performers) would pull every credit row for all of them into memory to then
count distinct artists per master -- the exact per-item/whole-table pattern
`credit_rows_for_release_batch`'s own docstring documents avoiding. This module
opens its own connection over the parquet globs, the same shape
`analysis.rank_album_candidates` already uses for a bulk analytical query.

Output is deliberately `rank-album-candidates`-shaped so it substitutes as
`score-expansion-candidates --candidates` and `select-graph-rich-candidates
--finalists` with no downstream change at all.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb

from .album_policy import master_non_studio_sql
from .eligibility import is_performer_role_sql
from .graph import _edge_ineligible_role_sql, _not_placeholder_sql, read_parquet_sql


def _progress(quiet: bool, message: str) -> None:
    """Coarse per-phase progress -- stderr only, never stdout (plan section 18 /
    slice 2-0b's convention)."""
    if not quiet:
        print(message, file=sys.stderr)


def performer_qualifying_credit_sql(
    *, role_column: str = "c.role_text", scope_column: str = "c.credit_scope"
) -> str:
    """SQL mirror of `pathfinding_graph.edge_eligible_membership_artist_ids`'s
    per-credit test: not an edge-ineligible role, AND either a billing scope
    (`release_artist`/`track_artist`, performer-qualifying regardless of role
    text -- including a bare NULL role) or a role text passing ADR 0068's
    performer gate.

    Kept here as one named helper rather than inlined twice below, so the pool
    side of the rule is visibly the same expression in both places it is used.
    """
    return (
        f"(NOT {_edge_ineligible_role_sql(role_column)} "
        f"AND ({scope_column} IN ('release_artist', 'track_artist') "
        f"OR {is_performer_role_sql(role_column)}))"
    )


def build_relationship_pool(
    dataset_root: str | Path,
    *,
    catalog_performer_ids: Iterable[int],
    masters_root: str | Path,
    allowed_release_ids: frozenset[int],
    minimum_overlap: int = 2,
    master_exclusions: frozenset[int] = frozenset(),
    already_published_master_ids: frozenset[int] = frozenset(),
    limit: int | None = None,
    memory_limit: str = "3GB",
    threads: int = 2,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Masters carrying at least `minimum_overlap` distinct catalog performers,
    ordered by that overlap descending then `master_id` for determinism.

    Rows are `rank-album-candidates`-shaped (`master_id`, `artist_id`,
    `artist_name`, `sample_title`, `main_release_id`, `year`) plus this
    module's own `catalog_performer_overlap`.

    `allowed_release_ids` gates the master's own main release by the
    studio-album policy, and `master_non_studio_sql` applies Discogs' editorial
    genre/style exclusion -- the same two gates `rank_album_candidates` applies,
    so this substitutes for it without loosening any policy. Full
    `master_eligibility` (which additionally checks that *some* release under
    the master is format-allowed, and picks the main release) still runs
    downstream in `score_expansion_candidates`; this is a pool filter, not a
    replacement for that verdict.

    `minimum_overlap` defaults to 2 because one shared performer adds a star,
    not structure -- `expansion-policy-v1.json`'s own
    `overlap_existing_minimum` for automatic lanes, and the plan's section 5.2
    hub-trap guard. Pass 1 for the collection-relaxed threshold.
    """
    performer_ids = sorted({int(a) for a in catalog_performer_ids})
    if not performer_ids:
        raise ValueError("catalog_performer_ids is empty -- the pool would be meaningless")

    start = time.monotonic()
    _progress(
        quiet,
        f"building relationship pool from {len(performer_ids)} catalog performers "
        f"(minimum_overlap={minimum_overlap})...",
    )

    dataset_root = Path(dataset_root)
    releases_glob = str(dataset_root / "table=releases" / "*.parquet")
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")
    masters_glob = str(Path(masters_root) / "table=masters" / "*.parquet")

    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute(f"SET threads = {int(threads)}")
        connection.execute(
            f"CREATE VIEW releases AS SELECT * FROM {read_parquet_sql(releases_glob)}"
        )
        connection.execute(f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}")
        connection.execute(f"CREATE VIEW masters AS SELECT * FROM {read_parquet_sql(masters_glob)}")

        # Only the performer set goes into a table -- it is ~3,000 rows. The
        # release-format allow-list is ~685,000 and must NEVER be loaded row by
        # row: an earlier draft did exactly that via `executemany` and the
        # command ran 33 minutes without finishing, while the aggregate it was
        # feeding takes ~53 seconds on its own (measured 2026-09-04). Bulk
        # alternatives are no better here -- passing the list as one `unnest`
        # parameter also failed to load inside 100s. The allow-list is instead
        # applied in Python below, against the few tens of thousands of rows
        # that survive aggregation rather than the 49M-row credits table.
        connection.execute("CREATE TABLE catalog_performers (artist_id BIGINT)")
        connection.executemany(
            "INSERT INTO catalog_performers VALUES (?)", [[a] for a in performer_ids]
        )

        exclusions_sql = ""
        excluded = sorted(master_exclusions | already_published_master_ids)
        if excluded:
            ids = ", ".join(str(int(mid)) for mid in excluded)
            exclusions_sql = f"AND m.master_id NOT IN ({ids})"

        rows = connection.execute(
            f"""
            WITH overlap AS (
                SELECT r.master_id AS master_id,
                       count(DISTINCT c.artist_id) AS catalog_performer_overlap
                FROM credits c
                JOIN releases r ON r.release_id = c.release_id
                WHERE c.artist_id IN (SELECT artist_id FROM catalog_performers)
                  AND c.playable_identity
                  AND c.artist_id IS NOT NULL
                  AND {_not_placeholder_sql("c.artist_id")}
                  AND {performer_qualifying_credit_sql()}
                  AND r.master_id IS NOT NULL
                GROUP BY r.master_id
                HAVING count(DISTINCT c.artist_id) >= {int(minimum_overlap)}
            )
            SELECT m.master_id,
                   m.main_release_id,
                   m.title,
                   m.year,
                   o.catalog_performer_overlap
            FROM overlap o
            JOIN masters m ON m.master_id = o.master_id
            WHERE m.main_release_id IS NOT NULL
              AND NOT {master_non_studio_sql("m.genres", "m.styles")}
              {exclusions_sql}
            ORDER BY o.catalog_performer_overlap DESC, m.master_id
            """
        ).fetchall()
        _progress(quiet, f"{len(rows)} masters cleared the overlap and genre gates")

        # The studio-album allow-list and `--limit` both apply here, in Python,
        # where the candidate set is already small.
        shortlisted = [row for row in rows if int(row[1]) in allowed_release_ids]
        if limit is not None:
            shortlisted = shortlisted[: int(limit)]
        _progress(
            quiet,
            f"{len(shortlisted)} remain after the studio-album allow-list"
            + (f" and --limit {limit}" if limit is not None else ""),
        )

        # The billed artist for each shortlisted master's main release, in ONE
        # query over a bounded id list rather than per candidate. Placeholder
        # identities are already excluded, so "Various Artists" can never head
        # a candidate -- the same guarantee `rank_album_candidates` relies on.
        artist_by_release: dict[int, tuple[int, str | None]] = {}
        main_release_ids = sorted({int(row[1]) for row in shortlisted})
        if main_release_ids:
            placeholders = ", ".join("?" for _ in main_release_ids)
            artists = connection.execute(
                f"""
                SELECT c.release_id, any_value(c.artist_id), any_value(c.name)
                FROM credits c
                WHERE c.credit_scope = 'release_artist'
                  AND c.playable_identity
                  AND c.artist_id IS NOT NULL
                  AND {_not_placeholder_sql("c.artist_id")}
                  AND c.release_id IN ({placeholders})
                GROUP BY c.release_id
                """,
                main_release_ids,
            ).fetchall()
            artist_by_release = {int(r): (aid, name) for r, aid, name in artists}
    finally:
        connection.close()

    pool: list[dict[str, Any]] = []
    for master_id, main_release_id, title, year, overlap_count in shortlisted:
        artist_id, artist_name = artist_by_release.get(int(main_release_id), (None, None))
        if artist_id is None:
            # No billed identity to publish under -- the same class
            # `rank_album_candidates` drops, dropped here too rather than
            # emitting a row that `greedy_marginal_selection` would crash on
            # (it indexes `artist_id` directly).
            continue
        pool.append(
            {
                "master_id": int(master_id),
                "artist_id": int(artist_id),
                "artist_name": artist_name,
                "sample_title": title,
                "main_release_id": int(main_release_id),
                "year": year,
                "catalog_performer_overlap": int(overlap_count),
            }
        )

    _progress(
        quiet,
        f"done in {time.monotonic() - start:.1f}s, {len(pool)} masters in the relationship pool",
    )
    return pool
