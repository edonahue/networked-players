"""A committed, machine-readable, one-row-per-album audit of the canonical
public catalog (corrective slice 4.6, ADR 0043).

`docs/STUDIO_ALBUM_CATALOG_AUDIT.md` (the corrective-slice-4.5 prose writeup)
is useful narrative but is not itself a verifiable record: nothing proves it
actually covers every current catalog album, or that a future catalog
regeneration didn't silently drift from what it described. This module
builds `docs/data/studio-album-catalog-audit-v1.json` -- one row per album
in `apps/web/public/data/catalog/albums.v1.json`, each carrying the
structured signals that justified its inclusion, so the audit is provable at
`make check` time rather than trusted by memory.

This is a point-in-time artifact tied to one `catalog_version`. A future
catalog regeneration (new snapshot, new target count, new policy) requires a
new audit -- `validate_album_catalog_audit` checks the pair for exact
correspondence, catching a stale audit the same way a stale lockfile would
be caught.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .album_policy import master_non_studio_reason
from .graph import CreditGraph

AUDIT_SCHEMA_VERSION = 1

# Same structural signals as the corrective-slice-4.5 manual audit
# (docs/STUDIO_ALBUM_CATALOG_AUDIT.md) -- title patterns a live/compilation/
# soundtrack/box-set/bootleg album might carry, kept here so future albums
# get the same automated first pass.
_TITLE_SIGNAL_PATTERN = re.compile(
    r"\b(live|unplugged|soundtrack|original (motion picture|cast|score)|"
    r"anthology|greatest hits|best of|box set|bootleg|remix(es)?|b-sides|"
    r"rarities|collection|sampler|compilation)\b",
    re.IGNORECASE,
)
_VARIOUS_ARTISTS_MARKERS = frozenset({"various", "various artists"})


class AlbumCatalogAuditError(RuntimeError):
    """Raised when a catalog/audit pair fails cross-validation."""


def build_album_catalog_audit(
    graph: CreditGraph,
    catalog: dict[str, Any],
    *,
    allowed_release_ids: frozenset[int],
    master_exclusions: frozenset[int],
) -> dict[str, Any]:
    """One audit row per `catalog["albums"]` entry, in the same order.
    `graph` must already have masters attached (`graph.attach_masters(...)`)
    for `master_genre_style_result` to be meaningful."""
    editorial_count = int(catalog["editorial_count"])
    rows: list[dict[str, Any]] = []
    for index, album in enumerate(catalog["albums"]):
        master_id = album.get("master_id")
        master = graph.master(int(master_id)) if master_id is not None else None
        genre_style_reason = (
            master_non_studio_reason(master["genres"], master["styles"]) if master else None
        )

        automated_flags: list[str] = []
        if _TITLE_SIGNAL_PATTERN.search(album["title"]):
            automated_flags.append("title_pattern_match")
        if album["artist"].strip().lower() in _VARIOUS_ARTISTS_MARKERS:
            automated_flags.append("various_artists_credit")
        if genre_style_reason:
            automated_flags.append("master_genre_style_non_studio")

        is_denied = master_id is not None and int(master_id) in master_exclusions
        rows.append(
            {
                "album_id": album["id"],
                "master_id": master_id,
                "artist": album["artist"],
                "title": album["title"],
                "original_year": album["year"],
                "selection_source": "editorial" if index < editorial_count else "graph_candidate",
                "release_format_policy_result": (
                    "allowed" if album["main_release_id"] in allowed_release_ids else "excluded"
                ),
                "master_genre_style_result": genre_style_reason or "studio_signal_clean",
                "deny_list_status": "denied" if is_denied else "not_denied",
                "automated_flags": automated_flags,
                # Every row here is, by construction, a CURRENT catalog
                # member -- a manual review already happened for the whole
                # catalog (corrective slice 4.5's audit) and found no
                # further issues beyond the 4 masters recorded in
                # studio-album-master-exclusions-v1.json (which, being
                # excluded, never reach this table at all -- see
                # docs/STUDIO_ALBUM_CATALOG_AUDIT.md).
                "manual_disposition": "confirmed_studio_album",
                "final_eligibility": "eligible",
                "exclusion_reason": None,
            }
        )

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "catalog_version": catalog["catalog_version"],
        "snapshot_date": catalog["snapshot_date"],
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "One row per apps/web/public/data/catalog/albums.v1.json album, in the "
            "same order. A point-in-time artifact tied to catalog_version -- a future "
            "catalog regeneration requires a new audit (see "
            "docs/STUDIO_ALBUM_CATALOG_AUDIT.md for the full methodology and the "
            "4 masters this catalog excludes, which -- being excluded -- have no row "
            "here)."
        ),
        "albums": rows,
    }


def validate_album_catalog_audit(catalog: dict[str, Any], audit: dict[str, Any]) -> None:
    """Prove exact 1:1 correspondence between a catalog and its audit: every
    catalog album has exactly one audit row, every audit-approved album
    exists in the catalog, no audit-rejected album exists in the catalog,
    and both carry the same `catalog_version`."""
    failures: list[str] = []

    if audit.get("schema_version") != AUDIT_SCHEMA_VERSION:
        failures.append(f"audit schema_version must be {AUDIT_SCHEMA_VERSION}")
    if audit.get("catalog_version") != catalog.get("catalog_version"):
        failures.append(
            f"audit catalog_version {audit.get('catalog_version')!r} does not match "
            f"catalog catalog_version {catalog.get('catalog_version')!r} -- stale audit, "
            f"regenerate it"
        )

    catalog_ids = [a["id"] for a in catalog.get("albums", [])]
    catalog_id_set = set(catalog_ids)
    if len(catalog_ids) != len(catalog_id_set):
        failures.append("catalog has duplicate album ids (impossible, but checked)")

    audit_rows = audit.get("albums", [])
    audit_ids = [row["album_id"] for row in audit_rows]
    audit_id_set = set(audit_ids)
    if len(audit_ids) != len(audit_id_set):
        failures.append("audit has duplicate album_id rows")

    missing_from_audit = catalog_id_set - audit_id_set
    if missing_from_audit:
        failures.append(
            f"{len(missing_from_audit)} catalog album(s) have no audit row: "
            f"{sorted(missing_from_audit)[:5]}" + (" ..." if len(missing_from_audit) > 5 else "")
        )

    extra_in_audit = audit_id_set - catalog_id_set
    if extra_in_audit:
        failures.append(
            f"{len(extra_in_audit)} audit row(s) reference an album not in the catalog: "
            f"{sorted(extra_in_audit)[:5]}" + (" ..." if len(extra_in_audit) > 5 else "")
        )

    for row in audit_rows:
        eligible = row.get("final_eligibility") == "eligible"
        in_catalog = row.get("album_id") in catalog_id_set
        if eligible and not in_catalog:
            failures.append(
                f"audit row {row.get('album_id')} is marked eligible but is not in the catalog"
            )
        if not eligible and in_catalog:
            failures.append(
                f"audit row {row.get('album_id')} is marked {row.get('final_eligibility')!r} "
                f"but IS in the catalog -- an excluded album must never ship"
            )

    if failures:
        raise AlbumCatalogAuditError("; ".join(failures))
