"""The approved-album pool (`data/albums/approved-pool-v1.json`, ADR 0072 s2).

A committed, cumulative list of every album approved for publication. It is
the one record that says "the owner approved exactly these"; generated
rankings and review packets never authorise publication, the pool does.

Deliberately minimal and public: per album only `master_id`, `round` (the
expansion round that added it) and `selection_source` (ADR 0069's PUBLIC enum,
so a personal-collection pick is `editorial`, never `personal_editorial`).
No scores, rejected or deferred candidates, reviewer identity or lane detail.
The validator rejects any extra key so the file cannot quietly grow private
fields.

Two checks:

- `approved_pool_failures`: the pool's own shape.
- `approved_pool_catalog_failures`: the catalog's master set must EQUAL the
  pool's, and where the catalog carries `expansion_round` /
  `selection_source` (catalog schema v2) they must agree per album.

`approved_pool_diff` is the shared primitive; the catalog builder uses it to
fail before writing an under- or over-delivering catalog.

Pure Python and dependency-free (runs on 1 GB Raspberry Pi workers).
"""

from __future__ import annotations

from typing import Any, TypeGuard

from .catalog import VALID_SELECTION_SOURCES

APPROVED_POOL_SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = frozenset({"schema_version", "note", "albums"})
_ALBUM_KEYS = frozenset({"master_id", "round", "selection_source"})


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def approved_pool_failures(pool: Any) -> list[str]:
    """Shape failures of the pool file itself."""
    if not isinstance(pool, dict):
        return ["approved pool must be a JSON object"]
    failures: list[str] = []
    extra = sorted(set(pool) - _TOP_LEVEL_KEYS)
    if extra:
        failures.append(f"approved pool has unexpected top-level keys: {extra}")
    if pool.get("schema_version") != APPROVED_POOL_SCHEMA_VERSION:
        failures.append(
            f"approved pool schema_version must be {APPROVED_POOL_SCHEMA_VERSION}, "
            f"got {pool.get('schema_version')!r}"
        )
    if not isinstance(pool.get("note"), str) or not pool["note"].strip():
        failures.append("approved pool needs a non-empty string 'note'")
    albums = pool.get("albums")
    if not isinstance(albums, list) or not albums:
        failures.append("approved pool 'albums' must be a non-empty list")
        return failures
    seen: set[int] = set()
    ids_in_order: list[int] = []
    for index, entry in enumerate(albums):
        if not isinstance(entry, dict):
            failures.append(f"approved pool albums[{index}] must be an object")
            continue
        keys = set(entry)
        if keys != _ALBUM_KEYS:
            failures.append(
                f"approved pool albums[{index}] must have exactly {sorted(_ALBUM_KEYS)}, "
                f"got {sorted(keys)}"
            )
        master_id = entry.get("master_id")
        if not _is_int(master_id) or master_id <= 0:
            failures.append(f"approved pool albums[{index}] has an invalid master_id")
        else:
            if master_id in seen:
                failures.append(f"approved pool lists master_id {master_id} more than once")
            seen.add(master_id)
            ids_in_order.append(master_id)
        round_number = entry.get("round")
        if not _is_int(round_number) or round_number < 0:
            failures.append(f"approved pool albums[{index}] has an invalid round")
        if entry.get("selection_source") not in VALID_SELECTION_SOURCES:
            failures.append(
                f"approved pool albums[{index}] has an invalid selection_source: "
                f"{entry.get('selection_source')!r}"
            )
    if ids_in_order != sorted(ids_in_order):
        failures.append("approved pool albums must be sorted by master_id (deterministic order)")
    return failures


def seed_approved_pool_from_catalog(catalog: dict[str, Any], *, note: str) -> dict[str, Any]:
    """Build a pool from a v2 catalog's own `master_id` / `expansion_round` /
    `selection_source` (deterministic: sorted by master_id). Used once to seed
    the pool from the published catalog (the pool follows the catalog, never
    the reverse); later rounds append owner-approved entries instead."""
    entries = []
    for album in catalog.get("albums", []):
        entries.append(
            {
                "master_id": album["master_id"],
                "round": album["expansion_round"],
                "selection_source": album["selection_source"],
            }
        )
    entries.sort(key=lambda e: e["master_id"])
    return {"schema_version": APPROVED_POOL_SCHEMA_VERSION, "note": note, "albums": entries}


def _pool_by_master(pool: Any) -> dict[int, dict[str, Any]]:
    albums = pool.get("albums") if isinstance(pool, dict) else None
    if not isinstance(albums, list):
        return {}
    return {
        e["master_id"]: e for e in albums if isinstance(e, dict) and _is_int(e.get("master_id"))
    }


def approved_pool_diff(
    pool: Any, catalog_albums: list[dict[str, Any]]
) -> tuple[list[int | None], list[int], list[str]]:
    """Compare a pool with catalog-shaped album dicts.

    Returns `(unapproved, missing, disagreements)`: master ids published but
    not approved (`None` stands for an album with no master id, which can
    never be approved), approved master ids absent from the catalog, and
    human-readable per-album `round`/`selection_source` disagreements (only
    where the catalog album carries those fields).
    """
    by_master = _pool_by_master(pool)
    catalog_masters: set[int] = set()
    unapproved: list[int | None] = []
    disagreements: list[str] = []
    for album in catalog_albums:
        master_id = album.get("master_id")
        if not _is_int(master_id):
            unapproved.append(None)
            continue
        catalog_masters.add(master_id)
        entry = by_master.get(master_id)
        if entry is None:
            unapproved.append(master_id)
            continue
        if "expansion_round" in album and album["expansion_round"] != entry.get("round"):
            disagreements.append(
                f"master {master_id}: catalog expansion_round {album['expansion_round']!r} "
                f"!= pool round {entry.get('round')!r}"
            )
        if "selection_source" in album and album["selection_source"] != entry.get(
            "selection_source"
        ):
            disagreements.append(
                f"master {master_id}: catalog selection_source {album['selection_source']!r} "
                f"!= pool selection_source {entry.get('selection_source')!r}"
            )
    missing = sorted(set(by_master) - catalog_masters)
    return unapproved, missing, disagreements


def approved_pool_catalog_failures(pool: Any, catalog: Any) -> list[str]:
    """Two-way check: catalog master set == pool master set, with per-album
    round / selection_source agreement."""
    if not isinstance(pool, dict):
        return []  # shape failure already reported by approved_pool_failures
    # A catalog this check cannot read is a failure of this check too, never a
    # pass: the catalog group reports the malformation, but "the pool agrees
    # with the catalog" must not be reported as true on its strength.
    if not isinstance(catalog, dict) or not isinstance(catalog.get("albums"), list):
        return ["catalog is missing or malformed; cannot compare it with the approved pool"]
    albums = catalog["albums"]
    catalog_masters = [a.get("master_id") for a in albums if isinstance(a, dict)]
    repeated = sorted(
        {m for m in catalog_masters if m is not None and catalog_masters.count(m) > 1}
    )
    unapproved, missing, disagreements = approved_pool_diff(
        pool, [a for a in albums if isinstance(a, dict)]
    )
    failures: list[str] = []
    if repeated:
        failures.append(f"catalog lists the same master more than once: {repeated}")
    if unapproved:
        failures.append(
            f"catalog publishes {len(unapproved)} album(s) not in the approved pool: {unapproved}"
        )
    if missing:
        failures.append(
            f"approved pool lists {len(missing)} album(s) absent from the catalog: {missing}"
        )
    failures.extend(disagreements)
    return failures
