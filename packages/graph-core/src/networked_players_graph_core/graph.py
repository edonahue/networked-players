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
from collections.abc import Sequence
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


class FrontierTooLargeError(GraphError):
    """Raised when `find_path`'s BFS hits an artist whose fan-out exceeds
    `max_frontier_expansion` and the target was never reached without
    expanding it. The result is inconclusive, not a confirmed absence of a
    path -- callers must not treat this the same as a `None` return."""

    def __init__(self, capped_artist_ids: frozenset[int]):
        self.capped_artist_ids = capped_artist_ids
        super().__init__(
            f"search hit artist(s) {sorted(capped_artist_ids)} exceeding "
            "max_frontier_expansion before reaching the target; result is "
            "inconclusive, not a confirmed no-path"
        )


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
        temp_dir: Path | None = None,
    ) -> CreditGraph:
        dataset_root = Path(dataset_root)
        manifest_path = dataset_root / "manifest.json"
        if not manifest_path.exists():
            raise GraphError(f"no manifest.json under {dataset_root}")

        credits_glob = str(dataset_root / "table=credits" / "*.parquet")
        releases_glob = str(dataset_root / "table=releases" / "*.parquet")

        # Without an explicit temp_directory, DuckDB spills to `.tmp/`
        # relative to the process's CWD -- on a host where CWD sits on a
        # small boot disk and the real dataset lives on a larger separate
        # volume, that silently risks a disk-full crash on a query that
        # spills. Default alongside the dataset itself, which is already
        # known to have room for a dataset this size.
        spill_dir = temp_dir if temp_dir is not None else dataset_root / ".graph-core-tmp"
        spill_dir.mkdir(parents=True, exist_ok=True)

        connection = duckdb.connect(database=":memory:")
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute(f"SET threads = {int(threads)}")
        connection.execute(f"SET temp_directory = '{spill_dir}'")

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

        # A materialized TABLE, not a VIEW: every BFS hop re-queries this
        # relation with a fresh WHERE/JOIN, and `linked_credits` has no
        # per-artist filter on its unfiltered join side (`neighbors()`'s `b`
        # side) -- left as a view, each of those queries re-scans and
        # re-filters the full underlying credits Parquet data from scratch.
        # Paying that scan once here (a hub artist's own neighbor lookup
        # measured at 1-2s materialized vs. not completing in 120s as a view)
        # is the same tradeoff `traversal_releases` below already makes.
        # Plain TABLE, not TEMP TABLE: DuckDB's TEMP schema is connection/
        # cursor-local, so a `cursor()` (see below) can't see a TEMP TABLE
        # created on its parent connection -- a plain table in an in-memory
        # database is exactly as ephemeral (gone when the connection closes)
        # but lives in the shared `main` schema every cursor can read.
        non_individual = ", ".join(str(i) for i in sorted(NON_INDIVIDUAL_ARTIST_IDS))
        connection.execute(
            "CREATE TABLE linked_credits AS "
            "SELECT release_id, artist_id, name FROM credits "
            "WHERE playable_identity AND artist_id IS NOT NULL AND artist_id > 0 "
            f"AND artist_id NOT IN ({non_individual})"
        )
        connection.execute(
            "CREATE TABLE traversal_releases AS "
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

    def cursor(self) -> CreditGraph:
        """A new `CreditGraph` sharing this one's underlying database --
        same materialized `linked_credits`/`traversal_releases` tables, same
        `credits`/`releases` views -- via an independent DuckDB cursor. Safe
        to use concurrently from another thread: each cursor has its own
        query/interrupt state, per DuckDB's own concurrency model, while
        reading the same already-materialized data with no re-scan cost."""
        return CreditGraph(
            self._connection.cursor(), max_artists_per_release=self._max_artists_per_release
        )

    def interrupt(self) -> None:
        """Cancel the currently running query on this graph's connection, if
        any. DuckDB's own supported cancellation primitive -- lets a caller
        enforce a wall-clock timeout around a single expensive call (e.g.
        `neighbors()`/`find_path()`) without corrupting the connection for
        subsequent calls."""
        self._connection.interrupt()

    def credit_row_count(self, artist_id: int) -> int:
        """A cheap upper-bound proxy for `artist_id`'s traversal fan-out:
        its own linked-credit row count, without the self-join `neighbors()`
        needs. Used to detect a likely hub before paying for that join."""
        row = self._connection.execute(
            "SELECT count(*) FROM linked_credits WHERE artist_id = ?", [artist_id]
        ).fetchone()
        assert row is not None
        return int(row[0])

    # One INSERT statement's worth of ids for `_scratch_id_table`. Bounds the
    # generated SQL text (~7 bytes/id -> ~350KB/statement) without giving up
    # the bulk win; scaling stays linear well past this size.
    _SCRATCH_INSERT_CHUNK = 50_000

    def _scratch_id_table(self, artist_ids: Sequence[int]) -> str:
        """A uniquely-named TEMP TABLE holding `artist_ids`, for a batched
        query's `JOIN`/`IN (SELECT ...)` -- callers are responsible for
        dropping it. TEMP TABLEs are cursor-local (not shared database-wide,
        unlike `linked_credits`/`traversal_releases`), which is exactly what
        we want here: pure per-call scratch state, never meant to be visible
        to another cursor.

        Population is one inline-literal `unnest` INSERT per chunk, not
        per-row `executemany`: measured on a real hub frontier, 17,612 ids
        took 54.3s to insert row-by-row while the batched query they fed took
        1.06s -- the insert, not the query, was blowing per-seed timeout
        budgets. Inline int literals measured ~170x faster than executemany
        and ~20x faster than a parameterized list bind at that size; `int()`
        coercion below keeps the inlining injection-safe."""
        table = f"scratch_ids_{uuid.uuid4().hex}"
        self._connection.execute(f"CREATE TEMP TABLE {table} (artist_id BIGINT)")
        for start in range(0, len(artist_ids), self._SCRATCH_INSERT_CHUNK):
            chunk = artist_ids[start : start + self._SCRATCH_INSERT_CHUNK]
            literals = ",".join(str(int(a)) for a in chunk)
            self._connection.execute(f"INSERT INTO {table} SELECT unnest([{literals}]::BIGINT[])")
        return table

    def credit_row_counts(self, artist_ids: Sequence[int]) -> dict[int, int]:
        """Batched `credit_row_count`: one query for the whole list instead
        of one per artist -- the same batching `find_path` already does for
        its own frontier-size check (see its `degrees` query below). An
        artist_id with zero linked credits is simply absent from the
        result -- callers should treat a missing key as 0, not an error."""
        if not artist_ids:
            return {}
        table = self._scratch_id_table(artist_ids)
        try:
            rows = self._connection.execute(
                "SELECT artist_id, count(*) FROM linked_credits "
                f"WHERE artist_id IN (SELECT artist_id FROM {table}) "
                "GROUP BY artist_id"
            ).fetchall()
        finally:
            self._connection.execute(f"DROP TABLE {table}")
        return {int(artist_id): int(count) for artist_id, count in rows}

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

    def neighbors_batch(self, artist_ids: Sequence[int]) -> dict[int, dict[int, tuple[int, ...]]]:
        """Batched `neighbors`: one self-join for every requested artist_id's
        fan-out instead of one query each -- the actual fix for a hub's
        hop-1 frontier (thousands of artists) each needing hop 2's own
        neighbor lookup. Every requested artist_id is a key in the result,
        even with an empty dict value, so callers can't mistake "not yet
        queried" for "queried, no neighbors"."""
        if not artist_ids:
            return {}
        table = self._scratch_id_table(artist_ids)
        try:
            rows = self._connection.execute(
                "SELECT a.artist_id, b.artist_id, "
                "list(DISTINCT a.release_id ORDER BY a.release_id) "
                "FROM linked_credits a "
                "JOIN linked_credits b USING (release_id) "
                "JOIN traversal_releases USING (release_id) "
                f"JOIN {table} f ON f.artist_id = a.artist_id "
                "WHERE b.artist_id != a.artist_id "
                "GROUP BY a.artist_id, b.artist_id ORDER BY a.artist_id, b.artist_id"
            ).fetchall()
        finally:
            self._connection.execute(f"DROP TABLE {table}")
        result: dict[int, dict[int, tuple[int, ...]]] = {int(a): {} for a in artist_ids}
        for a_id, b_id, release_ids in rows:
            result[int(a_id)][int(b_id)] = tuple(int(r) for r in release_ids)
        return result

    def find_path(
        self,
        from_artist_id: int,
        to_artist_id: int,
        *,
        max_hops: int = 4,
        max_frontier_expansion: int | None = None,
    ) -> EvidencePath | None:
        """Bounded BFS. `max_frontier_expansion`, when given, is a cheap
        release-count proxy threshold (see `credit_row_count`): a frontier
        artist above it is excluded from *expansion* this call (its own
        edges are never explored), though it can still be *reached* as a
        target via another artist's edges. If the target is never reached
        and any artist was excluded this way, raises `FrontierTooLargeError`
        instead of returning None -- the search result is inconclusive, not
        a confirmed no-path, and must never be reported as one."""
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
        capped_artist_ids: set[int] = set()
        try:
            for _ in range(max_hops):
                expand_from_table = frontier_table
                safe_table = f"safe_frontier_{suffix}"
                if max_frontier_expansion is not None:
                    degrees = self._connection.execute(
                        "SELECT artist_id, count(*) FROM linked_credits "
                        f"WHERE artist_id IN (SELECT artist_id FROM {frontier_table}) "
                        "GROUP BY artist_id"
                    ).fetchall()
                    newly_capped = {
                        int(artist_id)
                        for artist_id, release_count in degrees
                        if release_count > max_frontier_expansion
                    }
                    if newly_capped:
                        capped_artist_ids |= newly_capped
                        placeholders = ", ".join(str(a) for a in sorted(newly_capped))
                        self._connection.execute(
                            f"CREATE TEMP TABLE {safe_table} AS "
                            f"SELECT artist_id FROM {frontier_table} "
                            f"WHERE artist_id NOT IN ({placeholders})"
                        )
                        expand_from_table = safe_table

                level = self._connection.execute(
                    "SELECT a.artist_id, b.artist_id, min(b.release_id) "
                    "FROM linked_credits a "
                    "JOIN linked_credits b USING (release_id) "
                    "JOIN traversal_releases USING (release_id) "
                    f"JOIN {expand_from_table} f ON f.artist_id = a.artist_id "
                    "WHERE b.artist_id != a.artist_id "
                    f"AND b.artist_id NOT IN (SELECT artist_id FROM {visited_table}) "
                    "GROUP BY a.artist_id, b.artist_id "
                    "ORDER BY a.artist_id, b.artist_id"
                ).fetchall()

                if expand_from_table != frontier_table:
                    self._connection.execute(f"DROP TABLE {expand_from_table}")

                if not level:
                    if capped_artist_ids:
                        raise FrontierTooLargeError(frozenset(capped_artist_ids))
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

            if capped_artist_ids:
                raise FrontierTooLargeError(frozenset(capped_artist_ids))
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
