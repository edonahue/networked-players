"""A DuckDB-backed, evidence-preserving credit graph over a one-hop dataset.

Design decision: query-per-hop BFS over DuckDB views, never a materialized
in-Python adjacency. A one-hop corpus can hold hundreds of thousands of
credit rows; the coordination host's working budget is ~4GB. NetworkX or an
in-memory adjacency structure is the recorded revisit path if a measured
need appears (e.g. path lookups become a proven bottleneck) -- not assumed
up front. See AGENTS.md's "measured implementation need" requirement.

This package must not import from ``networked_players_catalog`` -- the
dependency direction is catalog CLI -> graph-core only, never the reverse.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

# Discogs reserves artist ID 194 for "Various" -- a compilation placeholder,
# not an individual. Excluded from the graph so a path never reads as a
# "connection" to a non-person. Kept as our own copy (not imported from
# catalog) per the no-reverse-dependency rule above.
NON_INDIVIDUAL_ARTIST_IDS = frozenset({194})

_CREDIT_COLUMNS = (
    "snapshot_date",
    "release_id",
    "track_index",
    "track_path",
    "track_position",
    "track_title",
    "credit_scope",
    "artist_id",
    "name",
    "anv",
    "join_text",
    "role_text",
    "credited_tracks_text",
    "is_linked",
    "playable_identity",
)


def read_parquet_sql(glob: str) -> str:
    """`read_parquet(...)` with Hive partitioning disabled.

    Every dataset in this project stores tables under
    `.../snapshot=<date>/table=<name>/*.parquet` -- DuckDB's default
    partition auto-detection reads those directory segments as columns and
    silently injects `snapshot`/`table` into every row of a `SELECT *`.
    """
    return f"read_parquet('{glob}', hive_partitioning = false)"


class GraphError(RuntimeError):
    """Raised when a graph can't be opened or queried as requested."""


@dataclass(frozen=True, slots=True)
class Hop:
    release_id: int
    artist_a_id: int
    artist_b_id: int


@dataclass(frozen=True, slots=True)
class EvidencePath:
    from_artist_id: int
    to_artist_id: int
    hops: tuple[Hop, ...]


class CreditGraph:
    """A lazy, DuckDB-backed view over one dataset's playable-identity credits."""

    def __init__(self, connection: duckdb.DuckDBPyConnection, *, max_artists_per_release: int):
        self._connection = connection
        self._max_artists_per_release = max_artists_per_release
        self._masters_attached = False

    @classmethod
    def open(
        cls,
        dataset_root: Path,
        *,
        memory_limit: str = "1GB",
        threads: int = 2,
        max_artists_per_release: int = 50,
    ) -> CreditGraph:
        dataset_root = Path(dataset_root)
        manifest_path = dataset_root / "manifest.json"
        if not manifest_path.exists():
            raise GraphError(f"no manifest.json under {dataset_root}")

        credits_glob = str(dataset_root / "table=credits" / "*.parquet")
        releases_glob = str(dataset_root / "table=releases" / "*.parquet")

        connection = duckdb.connect(database=":memory:")
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute(f"SET threads = {int(threads)}")

        try:
            connection.execute(
                f"CREATE VIEW credits AS SELECT * FROM {read_parquet_sql(credits_glob)}"
            )
            connection.execute(
                f"CREATE VIEW releases AS SELECT * FROM {read_parquet_sql(releases_glob)}"
            )
        except duckdb.IOException as exc:
            raise GraphError(f"could not open dataset at {dataset_root}: {exc}") from exc

        credit_count = connection.execute("SELECT count(*) FROM credits").fetchone()
        if credit_count is None or credit_count[0] == 0:
            raise GraphError(f"no credit rows found under {dataset_root}")

        non_individual = ", ".join(str(i) for i in sorted(NON_INDIVIDUAL_ARTIST_IDS))
        connection.execute(
            "CREATE VIEW linked_credits AS "
            "SELECT release_id, artist_id, name FROM credits "
            "WHERE playable_identity AND artist_id IS NOT NULL AND artist_id > 0 "
            f"AND artist_id NOT IN ({non_individual})"
        )
        connection.execute(
            "CREATE TEMP TABLE traversal_releases AS "
            "SELECT release_id FROM linked_credits GROUP BY release_id "
            f"HAVING count(DISTINCT artist_id) BETWEEN 2 AND {int(max_artists_per_release)}"
        )
        return cls(connection, max_artists_per_release=max_artists_per_release)

    def attach_masters(self, masters_root: Path) -> None:
        masters_root = Path(masters_root)
        masters_glob = str(masters_root / "table=masters" / "*.parquet")
        try:
            self._connection.execute(
                f"CREATE VIEW masters AS SELECT * FROM {read_parquet_sql(masters_glob)}"
            )
        except duckdb.IOException as exc:
            raise GraphError(f"could not open masters dataset at {masters_root}: {exc}") from exc
        self._masters_attached = True

    @property
    def masters_attached(self) -> bool:
        return self._masters_attached

    def neighbors(self, artist_id: int) -> dict[int, tuple[int, ...]]:
        rows = self._connection.execute(
            "SELECT b.artist_id, list(DISTINCT a.release_id ORDER BY a.release_id) "
            "FROM linked_credits a "
            "JOIN linked_credits b USING (release_id) "
            "JOIN traversal_releases USING (release_id) "
            "WHERE a.artist_id = ? AND b.artist_id != a.artist_id "
            "GROUP BY b.artist_id ORDER BY b.artist_id",
            [artist_id],
        ).fetchall()
        return {int(row[0]): tuple(int(r) for r in row[1]) for row in rows}

    def find_path(
        self, from_artist_id: int, to_artist_id: int, *, max_hops: int = 4
    ) -> EvidencePath | None:
        if from_artist_id == to_artist_id:
            raise GraphError("from_artist_id and to_artist_id must differ")

        suffix = uuid.uuid4().hex
        frontier_table = f"frontier_{suffix}"
        visited_table = f"visited_{suffix}"
        self._connection.execute(f"CREATE TEMP TABLE {frontier_table} (artist_id BIGINT)")
        self._connection.execute(f"CREATE TEMP TABLE {visited_table} (artist_id BIGINT)")
        self._connection.execute(f"INSERT INTO {frontier_table} VALUES (?)", [from_artist_id])
        self._connection.execute(f"INSERT INTO {visited_table} VALUES (?)", [from_artist_id])

        parent: dict[int, tuple[int, int]] = {}  # artist_id -> (parent_artist_id, release_id)
        try:
            for _ in range(max_hops):
                level = self._connection.execute(
                    "SELECT a.artist_id, b.artist_id, min(b.release_id) "
                    "FROM linked_credits a "
                    "JOIN linked_credits b USING (release_id) "
                    "JOIN traversal_releases USING (release_id) "
                    f"JOIN {frontier_table} f ON f.artist_id = a.artist_id "
                    "WHERE b.artist_id != a.artist_id "
                    f"AND b.artist_id NOT IN (SELECT artist_id FROM {visited_table}) "
                    "GROUP BY a.artist_id, b.artist_id "
                    "ORDER BY a.artist_id, b.artist_id"
                ).fetchall()

                if not level:
                    return None

                next_frontier: list[int] = []
                seen_this_level: set[int] = set()
                for from_id, to_id, release_id in level:
                    to_id = int(to_id)
                    if to_id in seen_this_level:
                        continue
                    seen_this_level.add(to_id)
                    parent[to_id] = (int(from_id), int(release_id))
                    next_frontier.append(to_id)
                    if to_id == to_artist_id:
                        return self._reconstruct_path(from_artist_id, to_artist_id, parent)

                self._connection.execute(f"DELETE FROM {frontier_table}")
                self._connection.executemany(
                    f"INSERT INTO {frontier_table} VALUES (?)",
                    [[a] for a in next_frontier],
                )
                self._connection.executemany(
                    f"INSERT INTO {visited_table} VALUES (?)",
                    [[a] for a in next_frontier],
                )

            return None
        finally:
            self._connection.execute(f"DROP TABLE {frontier_table}")
            self._connection.execute(f"DROP TABLE {visited_table}")

    @staticmethod
    def _reconstruct_path(
        from_artist_id: int, to_artist_id: int, parent: dict[int, tuple[int, int]]
    ) -> EvidencePath:
        hops: list[Hop] = []
        current = to_artist_id
        while current != from_artist_id:
            parent_id, release_id = parent[current]
            hops.append(Hop(release_id=release_id, artist_a_id=parent_id, artist_b_id=current))
            current = parent_id
        hops.reverse()
        return EvidencePath(
            from_artist_id=from_artist_id, to_artist_id=to_artist_id, hops=tuple(hops)
        )

    def credit_rows(self, release_id: int, artist_ids: set[int]) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in artist_ids)
        columns = ", ".join(_CREDIT_COLUMNS)
        rows = self._connection.execute(
            f"SELECT {columns} FROM credits "
            f"WHERE release_id = ? AND artist_id IN ({placeholders}) "
            "ORDER BY ALL",
            [release_id, *sorted(artist_ids)],
        ).fetchall()
        return [dict(zip(_CREDIT_COLUMNS, row, strict=True)) for row in rows]

    def release(self, release_id: int) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM releases WHERE release_id = ?", [release_id]
        ).fetchone()
        if row is None:
            return None
        columns = [d[0] for d in self._connection.description]
        return dict(zip(columns, row, strict=True))

    def find_release_by_title_artist(self, title: str, artist_name: str) -> dict[str, Any] | None:
        """The release-artist-scope playable credit matching an exact title + name/ANV.

        Prefers the master's main release, then the lowest release_id, so album
        matching is deterministic. Used to resolve an editorial {artist, title}
        query against real catalog rows.
        """
        row = self._connection.execute(
            "SELECT r.release_id, r.title, r.released, r.master_id, c.artist_id, c.name "
            "FROM releases r "
            "JOIN credits c USING (release_id) "
            "WHERE lower(r.title) = lower(?) "
            "AND c.credit_scope = 'release_artist' AND c.playable_identity "
            "AND (lower(c.name) = lower(?) OR lower(c.anv) = lower(?)) "
            "ORDER BY (r.master_is_main_release IS NOT TRUE), r.release_id",
            [title, artist_name, artist_name],
        ).fetchone()
        if row is None:
            return None
        return {
            "release_id": int(row[0]),
            "title": row[1],
            "released": row[2],
            "master_id": int(row[3]) if row[3] is not None else None,
            "artist_id": int(row[4]),
            "name": row[5],
        }

    def find_release_by_id_hint(
        self,
        *,
        release_id: int | None = None,
        master_id: int | None = None,
        artist_hint: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve a release from an explicit Discogs release_id or master_id,
        as opposed to `find_release_by_title_artist`'s text match. Exactly one
        of `release_id`/`master_id` should be given; `release_id` takes
        precedence if both are.

        A `release_id` that turns out to be a non-main pressing of a master is
        redirected to that master's actual main release, matching
        `find_release_by_title_artist`'s own main-release preference -- an
        explicit release_id hint should not overfit to a particular reissue.
        Returns None if the hint doesn't resolve to anything in this dataset
        (never guessed).
        """
        if release_id is not None:
            anchor = self._connection.execute(
                "SELECT master_id, master_is_main_release FROM releases WHERE release_id = ?",
                [release_id],
            ).fetchone()
            if anchor is None:
                return None
            anchor_master_id, is_main = anchor
            if anchor_master_id is None or is_main:
                return self._release_with_artist(release_id, artist_hint)
            master_id = int(anchor_master_id)

        if master_id is None:
            raise GraphError("find_release_by_id_hint needs release_id or master_id")

        main = self._connection.execute(
            "SELECT release_id FROM releases WHERE master_id = ? "
            "ORDER BY (master_is_main_release IS NOT TRUE), release_id LIMIT 1",
            [master_id],
        ).fetchone()
        if main is None:
            return None
        return self._release_with_artist(int(main[0]), artist_hint)

    def _release_with_artist(
        self, release_id: int, artist_hint: str | None
    ) -> dict[str, Any] | None:
        rows = self._connection.execute(
            "SELECT r.release_id, r.title, r.released, r.master_id, "
            "c.artist_id, c.name, c.anv "
            "FROM releases r JOIN credits c USING (release_id) "
            "WHERE r.release_id = ? AND c.credit_scope = 'release_artist' "
            "AND c.playable_identity "
            "ORDER BY c.artist_id",
            [release_id],
        ).fetchall()
        if not rows:
            return None

        chosen = rows[0]
        if artist_hint:
            lowered_hint = artist_hint.lower()
            for row in rows:
                if (row[5] and row[5].lower() == lowered_hint) or (
                    row[6] and row[6].lower() == lowered_hint
                ):
                    chosen = row
                    break

        return {
            "release_id": int(chosen[0]),
            "title": chosen[1],
            "released": chosen[2],
            "master_id": int(chosen[3]) if chosen[3] is not None else None,
            "artist_id": int(chosen[4]),
            "name": chosen[5],
        }

    def master(self, master_id: int) -> dict[str, Any] | None:
        """Row from the attached masters table, or None if not attached/found."""
        if not self._masters_attached:
            return None
        row = self._connection.execute(
            "SELECT title, year FROM masters WHERE master_id = ?", [master_id]
        ).fetchone()
        return None if row is None else {"title": row[0], "year": row[1]}

    def artist_name(self, artist_id: int) -> str | None:
        row = self._connection.execute(
            "SELECT name FROM linked_credits WHERE artist_id = ? "
            "GROUP BY name ORDER BY count(*) DESC, name LIMIT 1",
            [artist_id],
        ).fetchone()
        return None if row is None else str(row[0])

    def stats(self) -> dict[str, int]:
        artist_count = self._connection.execute(
            "SELECT count(DISTINCT artist_id) FROM linked_credits"
        ).fetchone()
        traversal_release_count = self._connection.execute(
            "SELECT count(*) FROM traversal_releases"
        ).fetchone()
        release_count = self._connection.execute(
            "SELECT count(DISTINCT release_id) FROM linked_credits"
        ).fetchone()
        assert artist_count is not None
        assert traversal_release_count is not None
        assert release_count is not None
        return {
            "artist_count": int(artist_count[0]),
            "traversal_release_count": int(traversal_release_count[0]),
            # Releases with a linked credit that don't drive traversal -- either
            # fewer than 2 distinct linked artists, or more than the cap.
            "non_traversal_release_count": int(release_count[0] - traversal_release_count[0]),
        }

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> CreditGraph:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
