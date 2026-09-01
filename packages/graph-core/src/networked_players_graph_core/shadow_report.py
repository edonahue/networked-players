"""ADR 0068 Performer Graph, PR 2: a shadow-build diagnostic comparing the
CURRENT (performer-gated) `credit_edges_sql` against a frozen, clearly-
labeled reconstruction of the PRE-ADR-0068 (broad) edge relation, on the
same real corpus. No production cutover happens here or anywhere in PR 2 --
this module only measures and reports.

`_broad_credit_edges_sql_pre_adr0068` is a deliberately frozen historical
snapshot of `credit_edges_sql` as it stood at commit `000a506` (the last
commit before ADR 0068's token expansion and this PR's performer gate),
reconstructed from `graph.py`'s own git history. It reuses `graph.py`'s
CURRENT helper functions for everything ADR 0068 did NOT change (the
`_NON_COLLABORATIVE_ROLE_TOKENS` denylist, placeholder/compilation/studio-
format guards) -- only the two `AND {performer_qualifying}` conditions
`credit_edges_sql` gained are omitted here, on purpose, to reconstruct the
"broad" relation for comparison. This is a one-time diagnostic copy, never
imported by production code, and must never be updated to track future
`credit_edges_sql` changes -- its whole point is staying frozen at the
pre-ADR-0068 baseline.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from .eligibility import is_performer_role
from .graph import (
    COMPILATION_TRACK_ARTIST_THRESHOLD,
    MAX_ARTISTS_PER_TRACK,
    _edge_ineligible_role_sql,
    _non_studio_release_title_sql,
    _non_studio_track_variant_sql,
    _not_placeholder_sql,
    credit_edges_sql,
)


def _broad_credit_edges_sql_pre_adr0068(
    *,
    max_artists_per_release: int,
    compilation_track_artist_threshold: int = COMPILATION_TRACK_ARTIST_THRESHOLD,
    max_artists_per_track: int = MAX_ARTISTS_PER_TRACK,
    credits_relation: str = "credits",
) -> str:
    """Frozen pre-ADR-0068 `credit_edges_sql` (commit `000a506`). See module
    docstring -- never updated, comparison-only."""
    ineligible = _edge_ineligible_role_sql("role_text")
    not_placeholder = _not_placeholder_sql()
    studio_track = _non_studio_track_variant_sql()
    studio_release = _non_studio_release_title_sql("r.title")
    cap = int(max_artists_per_release)
    track_cap = int(max_artists_per_track)
    return f"""
    WITH edge_credits AS (
        SELECT c.release_id, c.track_index, c.track_title, c.credit_scope, c.artist_id
        FROM {credits_relation} c
        JOIN releases r USING (release_id)
        WHERE c.playable_identity AND c.artist_id IS NOT NULL AND c.artist_id > 0
          AND {not_placeholder}
          AND NOT {ineligible}
          AND {studio_release}
    ), release_shape AS (
        SELECT release_id,
               count(DISTINCT CASE WHEN credit_scope = 'track_artist'
                                   THEN artist_id END) AS track_artist_count,
               count(DISTINCT CASE WHEN credit_scope = 'release_artist'
                                   THEN artist_id END) AS billed_artist_count,
               count(DISTINCT artist_id) AS artist_count
        FROM edge_credits GROUP BY release_id
    ), album_shaped AS (
        SELECT release_id FROM release_shape
        WHERE track_artist_count < {int(compilation_track_artist_threshold)}
          AND artist_count BETWEEN 2 AND {cap}
    ), single_billed AS (
        SELECT release_id FROM release_shape WHERE billed_artist_count = 1
    ), track_groups AS (
        SELECT release_id, track_index, min(track_title) AS track_title FROM edge_credits
        WHERE track_index IS NOT NULL
        GROUP BY release_id, track_index
        HAVING count(DISTINCT artist_id) <= {track_cap}
    ), billed_artists AS (
        SELECT DISTINCT release_id, artist_id FROM edge_credits
        WHERE credit_scope = 'release_artist'
    ), track_performers AS (
        SELECT release_id, track_index, artist_id FROM edge_credits
        WHERE credit_scope = 'track_artist' AND track_index IS NOT NULL
        UNION
        SELECT t.release_id, t.track_index, billed.artist_id
        FROM (SELECT DISTINCT release_id, track_index FROM edge_credits
              WHERE track_index IS NOT NULL) t
        JOIN track_groups tg USING (release_id, track_index)
        JOIN single_billed USING (release_id)
        JOIN album_shaped USING (release_id)
        JOIN edge_credits billed USING (release_id)
        WHERE billed.credit_scope = 'release_artist'
          AND NOT EXISTS (
              SELECT 1 FROM edge_credits x
              WHERE x.release_id = t.release_id AND x.track_index = t.track_index
                AND x.credit_scope = 'track_artist')
    ), same_recording AS (
        SELECT p.artist_id AS artist_a_id, c.artist_id AS artist_b_id, c.release_id
        FROM track_performers p
        JOIN edge_credits c USING (release_id, track_index)
        JOIN track_groups USING (release_id, track_index)
        WHERE p.artist_id <> c.artist_id AND c.credit_scope <> 'track_artist'
          AND {studio_track.replace("track_title", "c.track_title")}
          AND (
              EXISTS (SELECT 1 FROM billed_artists b
                      WHERE b.release_id = p.release_id AND b.artist_id = p.artist_id)
              OR EXISTS (SELECT 1 FROM billed_artists b
                         WHERE b.release_id = c.release_id AND b.artist_id = c.artist_id)
          )
    ), co_performers AS (
        SELECT p.artist_id AS artist_a_id, q.artist_id AS artist_b_id, p.release_id
        FROM track_performers p
        JOIN track_performers q USING (release_id, track_index)
        JOIN album_shaped USING (release_id)
        JOIN track_groups tg USING (release_id, track_index)
        JOIN billed_artists bp ON bp.release_id = p.release_id AND bp.artist_id = p.artist_id
        JOIN billed_artists bq ON bq.release_id = q.release_id AND bq.artist_id = q.artist_id
        WHERE p.artist_id <> q.artist_id
          AND {studio_track.replace("track_title", "tg.track_title")}
    ), release_scope AS (
        SELECT billed.artist_id AS artist_a_id, c.artist_id AS artist_b_id, billed.release_id
        FROM edge_credits billed
        JOIN edge_credits c USING (release_id)
        JOIN album_shaped USING (release_id)
        WHERE billed.credit_scope = 'release_artist'
          AND c.credit_scope = 'release_credit'
          AND billed.artist_id <> c.artist_id
    )
    SELECT DISTINCT artist_a_id, artist_b_id FROM (
        SELECT artist_a_id, artist_b_id FROM same_recording
        UNION ALL SELECT artist_b_id, artist_a_id FROM same_recording
        UNION ALL SELECT artist_a_id, artist_b_id FROM co_performers
        UNION ALL SELECT artist_a_id, artist_b_id FROM release_scope
        UNION ALL SELECT artist_b_id, artist_a_id FROM release_scope
    )
    """


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


@dataclass
class _GraphMetrics:
    node_count: int = 0
    directed_edge_count: int = 0
    undirected_edge_count: int = 0
    component_count: int = 0
    largest_component_size: int = 0
    catalog_albums_in_largest_component: int = 0
    isolated_catalog_anchors: list[int] = field(default_factory=list)
    isolated_catalog_album_count: int = 0
    degree_min: int = 0
    degree_max: int = 0
    degree_mean: float = 0.0
    degree_median: float = 0.0
    top_hubs: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count,
            "directed_edge_count": self.directed_edge_count,
            "undirected_edge_count": self.undirected_edge_count,
            "component_count": self.component_count,
            "largest_component_size": self.largest_component_size,
            "catalog_albums_in_largest_component": self.catalog_albums_in_largest_component,
            "isolated_catalog_anchors": self.isolated_catalog_anchors,
            "isolated_catalog_album_count": self.isolated_catalog_album_count,
            "degree_min": self.degree_min,
            "degree_max": self.degree_max,
            "degree_mean": round(self.degree_mean, 2),
            "degree_median": self.degree_median,
            "top_hubs": self.top_hubs,
        }


def _undirected_pairs(rows: list[tuple[int, int]]) -> set[tuple[int, int]]:
    return {(a, b) if a < b else (b, a) for a, b in rows if a != b}


def _compute_metrics(
    undirected: set[tuple[int, int]],
    directed_count: int,
    *,
    catalog_album_artist_ids: Sequence[int],
    catalog_names: dict[int, str],
    top_n_hubs: int = 15,
) -> _GraphMetrics:
    """`catalog_album_artist_ids` is one entry per real catalog ALBUM (its
    primary artist_id) -- duplicates preserved on purpose. A catalog artist
    with multiple albums (e.g. Jamiroquai, 5 of the real 179) must count as
    multiple albums here, not collapse to one: a `set` would under-report
    both `catalog_album_count` and `catalog_albums_in_largest_component`
    (round-1 Codex review finding on PR #204)."""
    metrics = _GraphMetrics()
    metrics.directed_edge_count = directed_count
    metrics.undirected_edge_count = len(undirected)

    degree: Counter[int] = Counter()
    uf = _UnionFind()
    for a, b in undirected:
        degree[a] += 1
        degree[b] += 1
        uf.union(a, b)
    nodes = set(degree)
    metrics.node_count = len(nodes)

    components: dict[int, int] = defaultdict(int)
    for node in nodes:
        components[uf.find(node)] += 1
    metrics.component_count = len(components)
    largest_root = max(components, key=lambda r: components[r]) if components else None
    metrics.largest_component_size = components[largest_root] if largest_root is not None else 0

    if largest_root is not None:
        in_largest = {n for n in nodes if uf.find(n) == largest_root}
    else:
        in_largest = set()
    metrics.catalog_albums_in_largest_component = sum(
        1 for aid in catalog_album_artist_ids if aid in in_largest
    )
    # Distinct artist ids, not one entry per album -- a listed id is worth
    # naming once regardless of how many of the artist's albums it isolates;
    # `isolated_catalog_album_count` below carries the real album-level count.
    metrics.isolated_catalog_anchors = sorted(
        {aid for aid in catalog_album_artist_ids if aid not in nodes}
    )
    metrics.isolated_catalog_album_count = sum(
        1 for aid in catalog_album_artist_ids if aid not in nodes
    )

    if degree:
        degrees = list(degree.values())
        metrics.degree_min = min(degrees)
        metrics.degree_max = max(degrees)
        metrics.degree_mean = statistics.mean(degrees)
        metrics.degree_median = statistics.median(degrees)
        metrics.top_hubs = [
            {
                "artist_id": aid,
                "degree": deg,
                "name": catalog_names.get(aid),
            }
            for aid, deg in degree.most_common(top_n_hubs)
        ]
    return metrics


@dataclass
class ShadowComparisonReport:
    dataset_root: str
    catalog_album_count: int
    catalog_primary_artist_count: int
    broad: dict[str, Any]
    gated: dict[str, Any]
    excluded_edges_by_role_text: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_root": self.dataset_root,
            "catalog_album_count": self.catalog_album_count,
            "catalog_primary_artist_count": self.catalog_primary_artist_count,
            "broad_pre_adr0068": self.broad,
            "gated_adr0068": self.gated,
            "excluded_edges_by_role_text": self.excluded_edges_by_role_text,
        }


def build_shadow_comparison_report(
    connection: duckdb.DuckDBPyConnection,
    *,
    dataset_root: str,
    catalog_album_artist_ids: Sequence[int],
    catalog_names: dict[int, str] | None = None,
    max_artists_per_release: int = 50,
    top_unmatched: int = 30,
) -> ShadowComparisonReport:
    """Real comparison over `connection`'s already-created `credits`/
    `releases` views: the current (ADR 0068, performer-gated) edge relation
    vs. the frozen pre-ADR-0068 (broad) reconstruction. Structural metrics
    only (node/edge/component counts, degree distribution, catalog-anchor
    connectivity) -- aggregate counts, not raw per-credit dumps, matching
    the same disclosure posture ADR 0068's own real-corpus audit table
    already used.

    `catalog_album_artist_ids` is one entry per real catalog ALBUM (its
    primary artist_id), duplicates preserved -- never deduplicate into a
    `set` before calling this: the real catalog has 179 albums but only 173
    distinct primary artists (e.g. 5 Jamiroquai albums), and a deduplicated
    set would under-report both `catalog_album_count` and
    `catalog_albums_in_largest_component` (round-1 Codex review finding on
    PR #204)."""
    names = catalog_names or {}

    gated_sql = credit_edges_sql(max_artists_per_release=max_artists_per_release)
    gated_rows = connection.execute(
        f"SELECT artist_a_id, artist_b_id FROM ({gated_sql})"
    ).fetchall()
    gated_undirected = _undirected_pairs([(int(a), int(b)) for a, b in gated_rows])
    gated_metrics = _compute_metrics(
        gated_undirected,
        len(gated_rows),
        catalog_album_artist_ids=catalog_album_artist_ids,
        catalog_names=names,
    )

    broad_sql = _broad_credit_edges_sql_pre_adr0068(max_artists_per_release=max_artists_per_release)
    broad_rows = connection.execute(
        f"SELECT artist_a_id, artist_b_id FROM ({broad_sql})"
    ).fetchall()
    broad_undirected = _undirected_pairs([(int(a), int(b)) for a, b in broad_rows])
    broad_metrics = _compute_metrics(
        broad_undirected,
        len(broad_rows),
        catalog_album_artist_ids=catalog_album_artist_ids,
        catalog_names=names,
    )

    # Excluded-edges-by-category: undirected pairs the broad relation had
    # but the gated one dropped, attributed to a real role_text sample
    # drawn from the credits that connected them (best-effort evidence, not
    # an exhaustive audit -- a pair can be connected by more than one
    # credit row).
    dropped = broad_undirected - gated_undirected
    excluded_role_counter: Counter[str] = Counter()
    if dropped:
        # Real, currently-unrecognized (is_performer_role == False)
        # release_credit/track_credit role texts, sampled from the full
        # extra-credit corpus rather than joined per dropped pair (a real
        # per-pair join at this scale is a materially heavier query for a
        # diagnostic that only needs "what kinds of roles are we now
        # correctly excluding"). Restricted to role texts `edge_ineligible_
        # role` does NOT already reject -- credit_edges_sql's universal
        # entry gate (ADR 0035's denylist) excludes those from BOTH the
        # broad and gated relations already, so a role like "Written-By"
        # was never edge-forming even pre-ADR-0068 and describing it as
        # "now excluded by the performer gate" would be false (round-1
        # Codex review finding on PR #204). This query describes the
        # actual delta: roles that survived ADR 0035's denylist but fail
        # ADR 0068's new allowlist.
        denylist_ineligible = _edge_ineligible_role_sql("role_text")
        role_rows = connection.execute(
            f"""
            SELECT role_text, count(*) AS n
            FROM credits
            WHERE credit_scope IN ('track_credit', 'release_credit')
              AND role_text IS NOT NULL
              AND NOT {denylist_ineligible}
            GROUP BY role_text
            ORDER BY n DESC
            LIMIT 500
            """
        ).fetchall()
        for role_text, n in role_rows:
            if role_text and not is_performer_role(role_text):
                excluded_role_counter[str(role_text)] += int(n)

    excluded_edges_by_role_text = [
        {"role_text": text, "count": count}
        for text, count in excluded_role_counter.most_common(top_unmatched)
    ]

    return ShadowComparisonReport(
        dataset_root=dataset_root,
        catalog_album_count=len(catalog_album_artist_ids),
        catalog_primary_artist_count=len(set(catalog_album_artist_ids)),
        broad=broad_metrics.as_dict(),
        gated=gated_metrics.as_dict(),
        excluded_edges_by_role_text=excluded_edges_by_role_text,
    )


def build_shadow_comparison_report_from_dataset(
    dataset_root: Path,
    *,
    catalog_album_artist_ids: Sequence[int],
    catalog_names: dict[int, str] | None = None,
    max_artists_per_release: int = 50,
) -> ShadowComparisonReport:
    """Thin CLI-facing wrapper: open a one-hop dataset's `credits`/
    `releases` tables read-only and run `build_shadow_comparison_report`
    over them, mirroring `corpus_coverage_report_from_dataset`'s shape."""
    credits_glob = str(Path(dataset_root) / "table=credits" / "*.parquet")
    releases_glob = str(Path(dataset_root) / "table=releases" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.read_parquet(credits_glob).create_view("credits")
        connection.read_parquet(releases_glob).create_view("releases")
        return build_shadow_comparison_report(
            connection,
            dataset_root=str(dataset_root),
            catalog_album_artist_ids=catalog_album_artist_ids,
            catalog_names=catalog_names,
            max_artists_per_release=max_artists_per_release,
        )
    finally:
        connection.close()
