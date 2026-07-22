"""Scoped, auditable group/frontperson exclusion artifact for game rounds.

Consumes a parsed `artist_relations` dataset (see `artists.py`) -- real,
numeric-ID-linked Discogs editorial data, never string resemblance -- and
publishes a small, committed artifact scoped only to a given launch's own
artist-ID universe (round endpoints and bridges, at most a few hundred IDs,
not the full ~10M-artist dump). This directly satisfies "auditable,
deterministic, tested" without inferring group membership from name matching.

Discogs' own `<groups>`/`<members>` tags are not guaranteed to be mirrored in
both directions on every record (a member's `<groups>` entry might exist
without a matching `<members>` entry on the group's own record, or vice
versa) -- `build_artist_family_exclusions` unions both directions so a
one-sided mirror still produces the relationship.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from networked_players_graph_core.graph import read_parquet_sql


def build_artist_family_exclusions(
    dataset_root: Path,
    *,
    artist_ids: Iterable[int],
    snapshot_date: str,
) -> dict[str, Any]:
    """Build a scoped person -> group_act_ids exclusion artifact.

    Only artists in `artist_ids` (the launch's own bounded universe) appear
    as a `person_id` entry -- this is what keeps the published artifact tiny
    and auditable rather than a copy of the full artist-relations dataset.
    """
    scoped = sorted({int(artist_id) for artist_id in artist_ids})
    if not scoped:
        raise ValueError("artist_ids must be non-empty")

    relations_glob = str(Path(dataset_root) / "table=artist_relations" / "*.parquet")
    ids_sql = ", ".join(str(i) for i in scoped)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            f"CREATE VIEW artist_relations AS SELECT * FROM {read_parquet_sql(relations_glob)}"
        )
        rows = connection.execute(
            """
            SELECT DISTINCT person_id, group_act_id FROM (
                SELECT artist_id AS person_id, related_artist_id AS group_act_id
                FROM artist_relations WHERE relation = 'member_of'
                UNION
                SELECT related_artist_id AS person_id, artist_id AS group_act_id
                FROM artist_relations WHERE relation = 'has_member'
            )
            """
            f"WHERE person_id IN ({ids_sql})"
            " ORDER BY person_id, group_act_id"
        ).fetchall()
    finally:
        connection.close()

    grouped: dict[int, list[int]] = {}
    for person_id, group_act_id in rows:
        grouped.setdefault(int(person_id), []).append(int(group_act_id))

    entries = [
        {
            "person_id": person_id,
            "group_act_ids": sorted(set(group_act_ids)),
            "source": "dump",
        }
        for person_id, group_act_ids in sorted(grouped.items())
    ]
    return {
        "schema_version": 1,
        "kind": "artist-family-exclusions",
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "entries": entries,
    }


def write_artist_family_exclusions(exclusions: dict[str, Any], output: Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    try:
        staging.write_text(json.dumps(exclusions, indent=2, sort_keys=True) + "\n")
        staging.replace(output)
    except Exception:
        staging.unlink(missing_ok=True)
        raise


def is_family_excluded_pair(artist_a_id: int, artist_b_id: int, exclusions: dict[str, Any]) -> bool:
    """True when two artists must not be paired in a round: one is a member
    of a group act the other's ID matches, or they share a group act (real
    or former bandmates).
    """
    if artist_a_id == artist_b_id:
        return True
    by_person = {
        int(entry["person_id"]): set(int(g) for g in entry["group_act_ids"])
        for entry in exclusions["entries"]
    }
    groups_a = by_person.get(artist_a_id, set())
    groups_b = by_person.get(artist_b_id, set())
    if artist_b_id in groups_a or artist_a_id in groups_b:
        return True
    return bool(groups_a & groups_b)
