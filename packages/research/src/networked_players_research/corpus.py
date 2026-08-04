"""Topic Corpus Builder: resolves a seed artist name to a real `artist_id`
and expands it into a bounded, versioned, snapshot-shaped corpus of
releases/tracks/credits -- Phase 3's artist-seeded generalization of
`packages/graph-core`'s one-hop expansion (`onehop.py`), which is
release-seeded from a private collection export only.

Deliberately mirrors `onehop.py`'s output *shape* exactly
(`table=releases`/`table=tracks`/`table=credits`/`table=release_formats`/
`manifest.json`, same DuckDB COPY/self-check pattern) so the result is a
drop-in input to `networked_players_graph_core.graph.CreditGraph.open()`
and every other existing snapshot-shaped tool -- no new graph-loading code
needed. Reuses `onehop.py`'s real, hardened placeholder-artist and
non-performer-role exclusions (`_NON_PLAYABLE_HUB_ARTIST_IDS`,
`_performer_credit_sql`) directly rather than re-deriving them --
`packages/research` is a new consumer, not `graph.py`/`challenge.py`/cohort
code, so the same import-a-private-helper pattern `role_taxonomy.py` and
`role_mode_candidates.py` already use for `eligibility.py` applies here too.

Privacy posture is the OPPOSITE of `onehop.py`'s: a topic corpus is about a
public subject (an artist), not the operator's private collection, so its
manifest records the resolved seed artist_id(s)/name(s) directly -- unlike
`onehop.py`, which deliberately omits the private seed's real release IDs.
A topic corpus is written under `local/research/<topic-slug>/corpus/`,
never `local/processed/discogs-onehop-v3/` (the private, collection-seeded
corpus) -- this module never reads that private corpus at all, only the
canonical full/parsed snapshot.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from networked_players_catalog.discogs.onehop import (
    _NON_PLAYABLE_HUB_ARTIST_IDS,
    _performer_credit_sql,
)
from networked_players_catalog.discogs.parquet import SCHEMA_VERSION, _sha256
from networked_players_contracts.canonical import content_hash

TOPIC_CORPUS_TABLES = ("releases", "tracks", "credits", "release_formats", "topic_seed_artists")

_TABLE_ORDER = {
    "releases": "ORDER BY release_id",
    "tracks": "ORDER BY ALL",
    "credits": "ORDER BY ALL",
    "release_formats": "ORDER BY release_id, format_index",
    "topic_seed_artists": "ORDER BY artist_id",
}


class TopicCorpusError(RuntimeError):
    """Raised when seed resolution or corpus construction cannot produce a
    valid, provable result."""


class AmbiguousSeedError(TopicCorpusError):
    """A seed name matched more than one distinct real artist_id -- never
    silently resolved to the first/most-credited match."""


class NoSeedMatchError(TopicCorpusError):
    """A seed name matched no artist_id in the dataset at all."""


@dataclass(frozen=True)
class SeedResolution:
    artist_id: int
    name: str
    matched_credits: int


def _rp(glob: str) -> str:
    return f"read_parquet('{glob}', hive_partitioning = false)"


def _scalar(
    connection: duckdb.DuckDBPyConnection, query: str, params: list[object] | None = None
) -> int:
    row = connection.execute(query, params or []).fetchone()
    if row is None:
        raise TopicCorpusError(f"query returned no row: {query}")
    return int(row[0])


def resolve_artist_seed(
    connection: duckdb.DuckDBPyConnection, name: str, *, credits_relation: str = "credits"
) -> SeedResolution:
    """Resolve `name` to a real `artist_id` via a `DISTINCT`/`GROUP BY`
    query over the dataset's own credit rows -- no Artist-dump ingestion
    required for this step. Case-insensitive, whitespace-trimmed exact
    match only; fuzzy matching is deliberately not attempted here (an
    ambiguous or missing match must be surfaced to a human, never guessed
    at)."""
    rows = connection.execute(
        f"""
        SELECT artist_id, name, count(*) AS credit_count
        FROM {credits_relation}
        WHERE artist_id IS NOT NULL AND lower(trim(name)) = lower(trim(?))
        GROUP BY artist_id, name
        ORDER BY credit_count DESC
        """,
        [name],
    ).fetchall()
    if not rows:
        raise NoSeedMatchError(f"no artist_id matches seed name {name!r}")
    distinct_artist_ids = {row[0] for row in rows}
    if len(distinct_artist_ids) > 1:
        raise AmbiguousSeedError(
            f"seed name {name!r} matches {len(distinct_artist_ids)} distinct artist_ids "
            f"({sorted(distinct_artist_ids)}) -- disambiguate with a more specific seed"
        )
    artist_id, matched_name, credit_count = rows[0]
    return SeedResolution(
        artist_id=int(artist_id), name=str(matched_name), matched_credits=int(credit_count)
    )


def build_topic_corpus(
    seed_artist_ids: Sequence[int],
    dataset_root: Path,
    output_root: Path,
    *,
    topic: str,
    hop_tier: int = 1,
    memory_limit: str = "2GB",
    threads: int = 2,
    temp_dir: Path | None = None,
    max_retained_releases: int | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """Expand `seed_artist_ids` one hop over a parsed snapshot at
    `dataset_root`, writing a new snapshot-shaped corpus under
    `output_root/snapshot=<date>/`. `hop_tier` must be 1 for now -- a
    deeper tier needs a real measured size check first
    (`GRAPH_BENCHMARK_METHOD.md`'s own finding that a 500-seed 2-hop ego
    network already balloons near full-corpus scale is the reason this
    isn't a silent default; see ADR 0054)."""
    if hop_tier != 1:
        raise TopicCorpusError(
            f"hop_tier={hop_tier} is not supported yet -- only hop_tier=1 is implemented; "
            "a deeper tier needs a real measured size check first, see ADR 0054"
        )
    if not seed_artist_ids:
        raise TopicCorpusError("seed_artist_ids must be non-empty")

    source_manifest_path = dataset_root / "manifest.json"
    if not source_manifest_path.is_file():
        raise TopicCorpusError(f"no manifest.json under {dataset_root} -- not a parsed snapshot")
    source_manifest = json.loads(source_manifest_path.read_text())
    if source_manifest.get("schema_version") not in (None, SCHEMA_VERSION):
        raise TopicCorpusError(
            f"source snapshot has schema_version={source_manifest.get('schema_version')!r}; "
            f"this builder understands schema_version={SCHEMA_VERSION} only"
        )
    snapshot_date = str(source_manifest["snapshot_date"])

    final_root = output_root / f"snapshot={snapshot_date}"
    if final_root.exists() and not overwrite:
        raise FileExistsError(f"corpus already exists: {final_root}")

    releases_glob = str(dataset_root / "table=releases" / "*.parquet")
    tracks_glob = str(dataset_root / "table=tracks" / "*.parquet")
    credits_glob = str(dataset_root / "table=credits" / "*.parquet")
    formats_glob = str(dataset_root / "table=release_formats" / "*.parquet")
    has_formats = Path(dataset_root / "table=release_formats").is_dir()

    staging_root = output_root / f".snapshot={snapshot_date}.tmp-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=False)
    spill_dir = temp_dir if temp_dir is not None else staging_root / ".duckdb-tmp"
    spill_dir.mkdir(parents=True, exist_ok=True)

    try:
        connection = duckdb.connect(database=":memory:")
        connection.execute(f"SET memory_limit='{memory_limit}'")
        connection.execute(f"SET threads={int(threads)}")
        connection.execute(f"SET temp_directory='{spill_dir}'")

        connection.execute("CREATE TEMP TABLE seed_artist_ids(artist_id BIGINT)")
        connection.executemany(
            "INSERT INTO seed_artist_ids VALUES (?)", [(int(a),) for a in seed_artist_ids]
        )

        hub_id_list = ", ".join(str(i) for i in sorted(_NON_PLAYABLE_HUB_ARTIST_IDS))
        performer_sql = _performer_credit_sql("role_text")

        # Tier 1: the frontier IS the seed -- no indirection through seed
        # releases (unlike onehop.py, which starts from release IDs and
        # derives an artist frontier from them).
        connection.execute(
            f"""
            CREATE TEMP TABLE frontier_artists AS
            SELECT DISTINCT artist_id FROM seed_artist_ids
            WHERE artist_id NOT IN ({hub_id_list or "-1"})
            """
        )
        frontier_count = _scalar(connection, "SELECT count(*) FROM frontier_artists")
        if frontier_count == 0:
            raise TopicCorpusError(
                "empty frontier: every seed artist_id was excluded as a non-playable "
                "placeholder identity"
            )

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
        if retained_count == 0:
            raise TopicCorpusError(
                "no releases retained: the seed artist has no performer-caliber credit "
                "in this snapshot"
            )
        if max_retained_releases is not None and retained_count > max_retained_releases:
            raise TopicCorpusError(
                f"retained release count {retained_count} exceeds the "
                f"max_retained_releases bound of {max_retained_releases}; nothing was written"
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
            "topic_seed_artists": "SELECT artist_id FROM seed_artist_ids",
        }
        if has_formats:
            table_sources["release_formats"] = (
                f"SELECT f.* FROM {_rp(formats_glob)} f "
                "WHERE f.release_id IN (SELECT release_id FROM retained_releases)"
            )

        counts: dict[str, int] = {}
        files: list[dict[str, object]] = []
        for table_name, select_sql in table_sources.items():
            table_dir = staging_root / f"table={table_name}"
            table_dir.mkdir(parents=True, exist_ok=True)
            out_path = table_dir / "part-00000.parquet"
            connection.execute(
                f"COPY ({select_sql} {_TABLE_ORDER[table_name]}) TO '{out_path}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 6, ROW_GROUP_SIZE 50000)"
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

        _self_check(connection, staging_root, counts, has_formats=has_formats)
        connection.close()
        shutil.rmtree(spill_dir, ignore_errors=True)

        corpus_version_seed = {
            "topic": topic,
            "hop_tier": hop_tier,
            "seed_artist_ids": sorted(int(a) for a in seed_artist_ids),
            "source_snapshot_date": snapshot_date,
        }
        manifest: dict[str, object] = {
            "dataset_manifest_version": 1,
            "schema_version": SCHEMA_VERSION,
            "source": "Discogs monthly data dumps (topic-corpus expansion)",
            "source_url": source_manifest.get("source_url"),
            "snapshot_date": snapshot_date,
            "generated_at": datetime.now(UTC).isoformat(),
            "compression": "zstd",
            "counts": counts,
            "files": files,
            "topic": {
                "kind": "topic-corpus",
                "topic": topic,
                "hop_tier": hop_tier,
                "seed_artist_ids": sorted(int(a) for a in seed_artist_ids),
                "corpus_version": (
                    f"research-corpus-v1-{snapshot_date}-{content_hash(corpus_version_seed)}"
                ),
                "frontier_artist_count": frontier_count,
                "retained_release_count": retained_count,
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


def _self_check(
    connection: duckdb.DuckDBPyConnection,
    staging_root: Path,
    counts: dict[str, int],
    *,
    has_formats: bool,
) -> None:
    tables = [t for t in TOPIC_CORPUS_TABLES if t != "release_formats" or has_formats]
    staged = {name: str(staging_root / f"table={name}" / "*.parquet") for name in tables}
    failures: dict[str, int] = {}

    unprovable = _scalar(
        connection,
        f"""
        SELECT count(*) FROM {_rp(staged["releases"])} r
        WHERE r.release_id NOT IN (
            SELECT release_id FROM {_rp(staged["credits"])}
            WHERE playable_identity
              AND artist_id IN (SELECT artist_id FROM {_rp(staged["topic_seed_artists"])})
        )
        """,
    )
    if unprovable:
        failures["releases_without_seed_evidence"] = unprovable

    for child in ("tracks", "credits", *(["release_formats"] if has_formats else [])):
        orphans = _scalar(
            connection,
            f"""
            SELECT count(*) FROM {_rp(staged[child])} c
            WHERE c.release_id NOT IN (SELECT release_id FROM {_rp(staged["releases"])})
            """,
        )
        if orphans:
            failures[f"orphan_{child}"] = orphans

    if counts["releases"] == 0:
        failures["empty_releases"] = 1

    if failures:
        raise TopicCorpusError(
            f"topic-corpus self-check failed: {json.dumps(failures, sort_keys=True)}"
        )
