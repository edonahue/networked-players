"""Scope-tier measurement (Phase 6 PR 6-11): turns the hand-run, one-off
"core discography vs. exploration neighborhood" measurement already
recorded for five real artists (`docs/NEXT_PATH_BRIEF.md`'s "Core-
discography vs. exploration-neighborhood corpus split" section;
`local/research/{jamiroquai,wu-tang-clan,d-angelo,nirvana,miles-davis}/
scope-tier-analysis.md`, gitignored) into reusable, tested code, so the
same measurement can be repeated on any built topic corpus without a
hand-rolled script.

Three tiers, each a strict narrowing of the full corpus already on disk
-- no new ingestion, and (per that measurement's own "what not to build
yet") no change to `corpus.py` or the Topic Corpus contract:

* **A -- full corpus**: every retained release, as built.
* **B -- direct-billed**: releases where the seed artist is the *sole*
  `release_artist`-scope credit (excludes shared-billing compilations).
* **C -- main-release-only**: B further filtered to
  `master_is_main_release = true` (collapses Discogs' regional/format/
  pressing duplication to one entry per real work).

The original measurement's Tier D ("studio albums only") is deliberately
NOT reproduced here: it was a hand-curated release-title list, not a
data-derived filter -- automating it would mean guessing at an "official
studio album" signal the dataset doesn't actually carry (ADR 0018's
"any sizing/classification claim must identify whether it is observed,
sourced, projected, or measured" applies to a classifier as much as a
number). Tier D stays a manual follow-up if a future decision needs it.

Graph structure reuses `graph.py`'s own production `credit_edges_sql` --
the same co-credit semantics the game traversal and
`graph_bench.py`'s benchmark use, never a simplified re-derivation.
Connected components are computed with a plain union-find rather than
pulling in the `graph` extra's `networkx`: this command is meant to run
with only the base install, and component-counting doesn't need a full
graph library.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb

from networked_players_graph_core.graph import credit_edges_sql
from networked_players_graph_core.role_taxonomy import RoleCategory, primary_role_category


class ScopeTierError(RuntimeError):
    """Raised when a corpus snapshot can't be measured (missing tables,
    unresolvable seed, etc.)."""


def _scalar(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise ScopeTierError(f"query returned no row: {query}")
    return int(row[0])


@dataclass(frozen=True)
class ScopeTierMetrics:
    tier: str
    description: str
    release_count: int
    credit_count: int
    distinct_contributor_count: int
    role_classified_fraction: float
    graph_node_count: int
    graph_edge_count: int
    component_count: int
    largest_component_size: int
    # The real, measured signature from the five-artist analysis: a
    # narrowed tier's co-credit graph collapses to a pure star/tree (edge
    # count == node count - 1, one component) -- everything connects only
    # through the seed artist, not to each other independently.
    star_topology: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _connected_components(edges: set[tuple[int, int]], nodes: set[int]) -> tuple[int, int]:
    """Plain union-find. Returns (component_count, largest_component_size).
    An empty node set is zero components of size zero, not an error."""
    parent = {n: n for n in nodes}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    sizes: dict[int, int] = {}
    for n in nodes:
        root = find(n)
        sizes[root] = sizes.get(root, 0) + 1
    if not sizes:
        return 0, 0
    return len(sizes), max(sizes.values())


def _tier_metrics(
    connection: duckdb.DuckDBPyConnection,
    *,
    tier: str,
    description: str,
    release_ids_table: str,
    max_artists_per_release: int,
) -> ScopeTierMetrics:
    release_count = _scalar(connection, f"SELECT count(*) FROM {release_ids_table}")
    if release_count == 0:
        return ScopeTierMetrics(
            tier=tier,
            description=description,
            release_count=0,
            credit_count=0,
            distinct_contributor_count=0,
            role_classified_fraction=0.0,
            graph_node_count=0,
            graph_edge_count=0,
            component_count=0,
            largest_component_size=0,
            star_topology=False,
        )

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW tier_credits AS
        SELECT * FROM credits_all WHERE release_id IN (SELECT release_id FROM {release_ids_table})
        """
    )
    role_rows = connection.execute("SELECT role_text FROM tier_credits").fetchall()
    credit_count = len(role_rows)
    classified = sum(
        1 for (role_text,) in role_rows if primary_role_category(role_text) != RoleCategory.UNKNOWN
    )
    distinct_contributor_count = _scalar(
        connection, "SELECT count(DISTINCT artist_id) FROM tier_credits"
    )

    connection.execute("CREATE OR REPLACE TEMP VIEW credits AS SELECT * FROM tier_credits")
    edge_sql = credit_edges_sql(max_artists_per_release=max_artists_per_release)
    edge_rows = connection.execute(f"SELECT artist_a_id, artist_b_id FROM ({edge_sql})").fetchall()
    edges = {(min(a, b), max(a, b)) for a, b in edge_rows if a != b}
    nodes: set[int] = set()
    for a, b in edges:
        nodes.add(a)
        nodes.add(b)
    component_count, largest_component_size = _connected_components(edges, nodes)
    star_topology = component_count == 1 and len(edges) == len(nodes) - 1 if nodes else False

    return ScopeTierMetrics(
        tier=tier,
        description=description,
        release_count=release_count,
        credit_count=credit_count,
        distinct_contributor_count=distinct_contributor_count,
        role_classified_fraction=round(classified / credit_count, 4) if credit_count else 0.0,
        graph_node_count=len(nodes),
        graph_edge_count=len(edges),
        component_count=component_count,
        largest_component_size=largest_component_size,
        star_topology=star_topology,
    )


def measure_scope_tiers(
    corpus_snapshot_root: Path,
    seed_artist_id: int,
    *,
    max_artists_per_release: int = 50,
) -> dict[str, Any]:
    """Measure tiers A/B/C over an already-built topic corpus snapshot
    (`research-build-corpus`'s own output shape). Raises `ScopeTierError`
    if the snapshot is missing the tables this needs."""
    for required_table in ("releases", "credits"):
        if not (corpus_snapshot_root / f"table={required_table}").is_dir():
            raise ScopeTierError(
                f"no table={required_table}/ under {corpus_snapshot_root} -- "
                "not a usable corpus snapshot"
            )

    releases_glob = str(corpus_snapshot_root / "table=releases" / "*.parquet")
    credits_glob = str(corpus_snapshot_root / "table=credits" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            f"CREATE VIEW releases AS SELECT * FROM read_parquet('{releases_glob}', "
            "hive_partitioning=false)"
        )
        connection.execute(
            f"CREATE VIEW credits_all AS SELECT * FROM read_parquet('{credits_glob}', "
            "hive_partitioning=false)"
        )

        connection.execute("CREATE TEMP TABLE tier_a_releases AS SELECT release_id FROM releases")

        connection.execute(
            f"""
            CREATE TEMP TABLE tier_b_releases AS
            SELECT release_id FROM (
                SELECT release_id, list(DISTINCT artist_id) AS billed_artists
                FROM credits_all
                WHERE credit_scope = 'release_artist'
                GROUP BY release_id
            )
            WHERE len(billed_artists) = 1 AND billed_artists[1] = {int(seed_artist_id)}
            """
        )

        connection.execute(
            """
            CREATE TEMP TABLE tier_c_releases AS
            SELECT r.release_id FROM releases r
            JOIN tier_b_releases b USING (release_id)
            WHERE r.master_is_main_release = true
            """
        )

        tiers = [
            _tier_metrics(
                connection,
                tier="A",
                description="full corpus, as built",
                release_ids_table="tier_a_releases",
                max_artists_per_release=max_artists_per_release,
            ),
            _tier_metrics(
                connection,
                tier="B",
                description="direct-billed: seed is the sole release_artist-scope credit",
                release_ids_table="tier_b_releases",
                max_artists_per_release=max_artists_per_release,
            ),
            _tier_metrics(
                connection,
                tier="C",
                description="direct-billed + main-release-only",
                release_ids_table="tier_c_releases",
                max_artists_per_release=max_artists_per_release,
            ),
        ]
    finally:
        connection.close()

    return {
        "corpus_snapshot": str(corpus_snapshot_root),
        "seed_artist_id": int(seed_artist_id),
        "max_artists_per_release": max_artists_per_release,
        "tiers": [t.to_dict() for t in tiers],
    }


def render_scope_tier_table(report: dict[str, Any]) -> str:
    """A compact Markdown table matching the shape of the existing
    hand-written `scope-tier-analysis.md` docs, for a human skimming
    `--output` or stdout."""
    header = (
        "| Tier | Releases | Credits | Distinct contributors | Role classified | "
        "Graph nodes | Graph edges | Components | Largest component | Star topology |"
    )
    separator = "|---|---|---|---|---|---|---|---|---|---|"
    lines = [header, separator]
    for tier in report["tiers"]:
        lines.append(
            "| {tier} | {release_count} | {credit_count} | {distinct_contributor_count} | "
            "{role_classified_pct:.1f}% | {graph_node_count} | {graph_edge_count} | "
            "{component_count} | {largest_component_size} | {star} |".format(
                tier=tier["tier"],
                release_count=tier["release_count"],
                credit_count=tier["credit_count"],
                distinct_contributor_count=tier["distinct_contributor_count"],
                role_classified_pct=tier["role_classified_fraction"] * 100,
                graph_node_count=tier["graph_node_count"],
                graph_edge_count=tier["graph_edge_count"],
                component_count=tier["component_count"],
                largest_component_size=tier["largest_component_size"],
                star="yes" if tier["star_topology"] else "no",
            )
        )
    return "\n".join(lines)
