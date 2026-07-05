"""Milestone 5: one-hop catalog expansion from the private seed.

Turns the seed's release IDs plus a parsed full snapshot into the
frontier-and-filter one-hop corpus `docs/DISCOGS_INGESTION.md` describes:

1. frontier = every *playable* (linked, positive-ID) credited artist on any
   seed release;
2. retained = every release in the snapshot with a playable credit by a
   frontier artist (seed releases are necessarily retained -- their own
   credits are frontier credits by construction);
3. output = a new, versioned, immutable dataset containing the retained
   subset of ``releases``/``tracks``/``credits`` (ALL credit rows of every
   retained release, including non-linked evidence rows -- no shortcut that
   drops evidence), plus two expansion-specific tables:
   ``frontier_artists`` and ``seed_releases``.

Everything heavy runs inside DuckDB with an explicit memory limit and a
spill directory -- the 220M-row credits table streams through two
projection-pushed scans and per-table ``COPY`` statements; full rows never
enter Python memory.

Privacy posture: the output dataset is seed-derived and therefore private
by location -- it is written under the git-ignored ``local/`` tree, same as
the full snapshot, and must never be committed or published. Committed
tests use only synthetic seeds and fixtures. The output manifest records
seed *aggregates* (count, sha256 of the sorted ID list) for provenance,
never the IDs themselves and never a private filesystem path.

Non-playable credits never create frontier membership or drive retention
(the standing evidence rule: non-linked names are evidence, not playable
identities). Two further, narrower exclusions apply to frontier/retention
eligibility only (never to evidence -- a retained release still keeps every
credit row regardless of these exclusions):

- A small, fixed set of Discogs *placeholder* identities (real, linked
  artist IDs that are not actual performers -- "Various Artists", "Trad.")
  are excluded: see `_NON_PLAYABLE_HUB_ARTIST_IDS` and ADR 0026.
- Credits whose role is *purely* production/writing/business (every
  comma-separated role component is a known non-performer token -- "Written-By",
  "Mastered By", "Producer", etc.) are excluded: see
  `_NON_PERFORMER_ROLE_TOKENS` and ADR 0027. A main-artist credit (no role
  text at all) is always eligible.

Both are documented in full, with the real-data investigation behind them,
in `docs/discogs-data/one-hop-hub-artists.md`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from networked_players_catalog import __version__

from .parquet import SCHEMA_VERSION, _sha256
from .seed import SeedManifest

ONEHOP_TABLES = ("releases", "tracks", "credits", "frontier_artists", "seed_releases")

# Deterministic output ordering per table. `ORDER BY ALL` sorts by every
# column left-to-right, which makes the row order a pure function of the row
# *content* -- ties can only occur between byte-identical rows, so the
# written files are reproducible across runs even with threads > 1.
_TABLE_ORDER = {
    "releases": "ORDER BY release_id",
    "tracks": "ORDER BY ALL",
    "credits": "ORDER BY ALL",
    "frontier_artists": "ORDER BY artist_id",
    "seed_releases": "ORDER BY release_id",
}


class OneHopError(RuntimeError):
    """Raised when the one-hop expansion cannot produce a valid corpus."""


# Discogs canonical placeholder identities: each carries a real, linked
# artist_id (playable_identity=True per parquet.py's PAN-linkage rule) but is
# not an actual performer. Left eligible for frontier membership, a single
# compilation LP or heavily-covered traditional-song release in the seed
# would pull in a huge, musically meaningless slice of the whole catalog --
# "Various Artists" (194) alone is credited on 1.3M+ of 19.2M releases in the
# 2026-06-01 snapshot (~7% of the entire catalog from one identity). Real,
# individually prolific human contributors (mastering engineers, heavily
# covered songwriters) are deliberately NOT excluded here -- those are
# legitimate, if broad, connections. See
# docs/discogs-data/one-hop-hub-artists.md for the full investigation and
# ADR 0026 for the decision.
_NON_PLAYABLE_HUB_ARTIST_IDS = frozenset(
    {
        194,  # "Various Artists" -- Discogs' compilation-album placeholder
        151641,  # "Trad." -- Discogs' placeholder for traditional/anonymous composers
    }
)

# Role-text tokens treated as pure production/writing/business credits, not a
# performance -- excluded from frontier/retention eligibility (but never from
# evidence: a retained release still keeps every credit row). role_text is
# freeform and comma-combined (e.g. "Producer, Mixed By, Arranged By"), so a
# credit only counts as "non-performer" when EVERY comma-separated component
# matches this list; a single unlisted or performer-type component (Vocals,
# Guitar, Featuring, ...) keeps the whole credit eligible. A NULL role_text is
# a main-artist credit (from a release's own <artists> block) and is always
# eligible -- it is never filtered by this list. "Producer" is deliberately
# included here even though it's a debatable case (arguably more personal
# than a mastering credit) -- see docs/discogs-data/one-hop-hub-artists.md and
# ADR 0027 for the investigation and reasoning. An unlisted role always
# defaults to "keep" (eligible), never "exclude" -- an incomplete list can
# only under-filter, never silently over-filter.
_NON_PERFORMER_ROLE_TOKENS = frozenset(
    {
        "written-by",
        "written by",
        "mastered by",
        "mixed by",
        "recorded by",
        "lacquer cut by",
        "arranged by",
        "liner notes",
        "composed by",
        "lyrics by",
        "music by",
        "words by",
        "engineer",
        "producer",
        "co-producer",
        "design",
        "design concept",
        "photography by",
    }
)


def _performer_credit_sql(role_column: str) -> str:
    """SQL boolean expression: true when a credit counts as performer-caliber.

    True when `role_column` is NULL (a main-artist credit) or contains at
    least one comma-separated component that is not a known
    `_NON_PERFORMER_ROLE_TOKENS` entry. False only when every component of a
    non-null role is a known non-performer token.
    """
    tokens = ", ".join(f"'{token}'" for token in sorted(_NON_PERFORMER_ROLE_TOKENS))
    return f"""(
        {role_column} IS NULL
        OR list_bool_or(
            list_transform(
                str_split({role_column}, ','),
                x -> NOT (lower(trim(regexp_replace(x, '\\[.*\\]', ''))) IN ({tokens}))
            )
        )
    )"""


def _copy_options() -> str:
    return "FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 6, ROW_GROUP_SIZE 50000"


def _rp(glob: str) -> str:
    """`read_parquet(...)` with Hive partitioning disabled.

    Every dataset here lives under `.../snapshot=<date>/table=<name>/*.parquet`
    -- DuckDB's default partition auto-detection reads those directory
    segments as columns and silently injects `snapshot`/`table` into every
    row of a `SELECT *`/`r.*`, which would otherwise get written straight
    into this module's output tables.
    """
    return f"read_parquet('{glob}', hive_partitioning = false)"


def expand_one_hop(
    seed_path: Path,
    dataset_root: Path,
    output_root: Path,
    *,
    memory_limit: str = "3GB",
    threads: int = 2,
    temp_dir: Path | None = None,
    max_retained_releases: int | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """Expand the seed one hop over a parsed snapshot; returns the manifest."""

    source_manifest_path = dataset_root / "manifest.json"
    if not source_manifest_path.is_file():
        raise OneHopError(f"no manifest.json under {dataset_root} -- not a parsed snapshot")
    source_manifest = json.loads(source_manifest_path.read_text())
    if source_manifest.get("schema_version") != SCHEMA_VERSION:
        raise OneHopError(
            f"source snapshot has schema_version={source_manifest.get('schema_version')!r}; "
            f"this expansion understands schema_version={SCHEMA_VERSION} only"
        )
    snapshot_date = str(source_manifest["snapshot_date"])

    seed = SeedManifest.read(seed_path)
    seed_digest = hashlib.sha256(json.dumps(sorted(seed.release_ids)).encode("utf-8")).hexdigest()

    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {final_root}")

    releases_glob = str(dataset_root / "table=releases" / "*.parquet")
    tracks_glob = str(dataset_root / "table=tracks" / "*.parquet")
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")

    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)
    spill_dir = temp_dir if temp_dir is not None else staging_root / ".duckdb-tmp"
    spill_dir.mkdir(parents=True, exist_ok=True)

    try:
        connection = duckdb.connect(database=":memory:")
        connection.execute(f"SET memory_limit='{memory_limit}'")
        connection.execute(f"SET threads={int(threads)}")
        connection.execute(f"SET temp_directory='{spill_dir}'")

        connection.execute("CREATE TEMP TABLE seed_release_ids(release_id BIGINT)")
        connection.executemany(
            "INSERT INTO seed_release_ids VALUES (?)",
            [(release_id,) for release_id in seed.release_ids],
        )

        # Pass 1 over credits: the artist frontier. Projection pushdown means
        # only release_id/artist_id/playable_identity/role_text are read from
        # disk. Placeholder identities (_NON_PLAYABLE_HUB_ARTIST_IDS) and
        # pure non-performer role credits (_NON_PERFORMER_ROLE_TOKENS) are
        # excluded here so neither drives retention in pass 2 below.
        hub_id_list = ", ".join(str(i) for i in sorted(_NON_PLAYABLE_HUB_ARTIST_IDS))
        performer_sql = _performer_credit_sql("role_text")
        connection.execute(
            f"""
            CREATE TEMP TABLE frontier_artists AS
            SELECT DISTINCT artist_id
            FROM {_rp(credits_glob)}
            WHERE playable_identity
              AND artist_id NOT IN ({hub_id_list})
              AND {performer_sql}
              AND release_id IN (SELECT release_id FROM seed_release_ids)
            """
        )
        frontier_count = _scalar(connection, "SELECT count(*) FROM frontier_artists")
        if frontier_count == 0:
            raise OneHopError(
                "empty frontier: no seed release has a playable (linked) credited artist "
                "in this snapshot -- check that the seed matches the snapshot"
            )

        # Pass 2 over credits: retention. The frontier is the tiny hash-build
        # side; the 220M-row scan streams row-group by row-group. The same
        # performer-credit filter applies here -- a frontier artist's own
        # pure non-performer credit elsewhere should not retain that release
        # either, matching pass 1's standard.
        connection.execute(
            f"""
            CREATE TEMP TABLE retained_releases AS
            SELECT DISTINCT release_id
            FROM {_rp(credits_glob)}
            WHERE playable_identity
              AND {performer_sql}
              AND artist_id IN (SELECT artist_id FROM frontier_artists)
            """
        )
        retained_count = _scalar(connection, "SELECT count(*) FROM retained_releases")
        if max_retained_releases is not None and retained_count > max_retained_releases:
            raise OneHopError(
                f"retained release count {retained_count} exceeds the "
                f"--max-retained-releases bound of {max_retained_releases}; "
                "nothing was written"
            )

        seed_missing = _scalar(
            connection,
            f"""
            SELECT count(*) FROM seed_release_ids s
            WHERE s.release_id NOT IN (
                SELECT release_id FROM {_rp(releases_glob)}
            )
            """,
        )

        table_sources = {
            "releases": (
                f"SELECT r.* FROM {_rp(releases_glob)} r "
                "WHERE r.release_id IN (SELECT release_id FROM retained_releases)"
            ),
            "tracks": (
                f"SELECT t.* FROM {_rp(tracks_glob)} t "
                "WHERE t.release_id IN (SELECT release_id FROM retained_releases)"
            ),
            "credits": (
                f"SELECT c.* FROM {_rp(credits_glob)} c "
                "WHERE c.release_id IN (SELECT release_id FROM retained_releases)"
            ),
            "frontier_artists": "SELECT artist_id FROM frontier_artists",
            "seed_releases": (
                "SELECT s.release_id FROM seed_release_ids s "
                f"WHERE s.release_id IN (SELECT release_id FROM {_rp(releases_glob)})"
            ),
        }

        counts: dict[str, int] = {}
        files: list[dict[str, object]] = []
        for table_name, select_sql in table_sources.items():
            table_dir = staging_root / f"table={table_name}"
            table_dir.mkdir(parents=True, exist_ok=True)
            out_path = table_dir / "part-00000.parquet"
            connection.execute(
                f"COPY ({select_sql} {_TABLE_ORDER[table_name]}) "
                f"TO '{out_path}' ({_copy_options()})"
            )
            rows = int(pq.ParquetFile(out_path).metadata.num_rows)
            counts[table_name] = rows
            files.append(
                {
                    "path": str(out_path.relative_to(staging_root)),
                    "size_bytes": out_path.stat().st_size,
                    "sha256": _sha256(out_path),
                    "rows": rows,
                }
            )

        _self_check(connection, staging_root, counts)
        connection.close()

        shutil.rmtree(spill_dir, ignore_errors=True)

        manifest: dict[str, object] = {
            "dataset_manifest_version": 1,
            "schema_version": SCHEMA_VERSION,
            "parser_version": __version__,
            "source": "Discogs monthly data dumps (one-hop expansion)",
            "source_url": source_manifest.get("source_url"),
            "snapshot_date": snapshot_date,
            "generated_at": datetime.now(UTC).isoformat(),
            "compression": "zstd",
            "counts": counts,
            "files": files,
            "expansion": {
                "kind": "one-hop",
                "source_snapshot_date": snapshot_date,
                "source_manifest_sha256": _sha256(source_manifest_path),
                "seed_version": seed.seed_version,
                "seed_release_count": len(seed.release_ids),
                "seed_sha256": seed_digest,
                "frontier_artist_count": frontier_count,
                "retained_release_count": retained_count,
                "seed_releases_missing_from_snapshot": seed_missing,
            },
        }
        (staging_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        if final_root.exists():
            shutil.rmtree(final_root)
        staging_root.replace(final_root)
        return manifest
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def _scalar(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise OneHopError(f"query returned no row: {query}")
    return int(row[0])


def _self_check(
    connection: duckdb.DuckDBPyConnection, staging_root: Path, counts: dict[str, int]
) -> None:
    """Onehop-specific invariants, checked against the staged files before the
    atomic rename -- a failed check aborts the whole expansion rather than
    publishing a corpus that cannot prove its own edges."""

    staged = {name: str(staging_root / f"table={name}" / "*.parquet") for name in ONEHOP_TABLES}
    failures: dict[str, int] = {}

    seed_not_retained = _scalar(
        connection,
        f"""
        SELECT count(*) FROM {_rp(staged["seed_releases"])} s
        WHERE s.release_id NOT IN
            (SELECT release_id FROM {_rp(staged["releases"])})
        """,
    )
    if seed_not_retained:
        failures["seed_releases_not_retained"] = seed_not_retained

    unprovable = _scalar(
        connection,
        f"""
        SELECT count(*) FROM {_rp(staged["releases"])} r
        WHERE r.release_id NOT IN (
            SELECT release_id FROM {_rp(staged["credits"])}
            WHERE playable_identity
              AND artist_id IN
                (SELECT artist_id FROM {_rp(staged["frontier_artists"])})
        )
        """,
    )
    if unprovable:
        failures["releases_without_frontier_evidence"] = unprovable

    for child in ("tracks", "credits"):
        orphans = _scalar(
            connection,
            f"""
            SELECT count(*) FROM {_rp(staged[child])} c
            WHERE c.release_id NOT IN
                (SELECT release_id FROM {_rp(staged["releases"])})
            """,
        )
        if orphans:
            failures[f"orphan_{child}"] = orphans

    if counts["releases"] == 0:
        failures["empty_releases"] = 1

    if failures:
        raise OneHopError(f"one-hop self-check failed: {json.dumps(failures, sort_keys=True)}")
