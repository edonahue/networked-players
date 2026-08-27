"""Assemble the Phase 7 catalog-expansion review packet.

Combines Bucket A (personal/editorial), Bucket B (graph-rich), and Bucket C
(coverage-gap) sources into one human-reviewable structure. This module
never promotes anything and never writes to any catalog artifact -- the
reviewed selection becoming a build input remains a separate, explicit,
human-driven step (`docs/PUBLIC_PRIVATE_BOUNDARY.md`).

This is currently a STANDALONE packet, not yet wired into any UI: as of
this module's own introduction, `apps/review` has no expansion-review mode
-- its existing `review_server.py` only serves the cohort-pair review page
described in `apps/review/README.md`. A future curator extension may
consume this packet's JSON; until that lands, `build-expansion-review-packet`
is a CLI-and-file workflow (inspect the written JSON directly).

Output is written under `data/private/catalog-expansion/` (gitignored,
agent-read-denied) -- richer and more revealing than the committed
`data/albums/editorial-seed-v1.json` is allowed to be, precisely because it
never leaves this machine.
"""

from __future__ import annotations

from typing import Any

EXPANSION_REVIEW_SCHEMA_VERSION = 1
_BUCKETS = ("personal", "graph_rich", "coverage_gap")


def _entry(bucket: str, album: dict[str, Any], already_in_catalog: bool) -> dict[str, Any]:
    base = {
        "bucket": bucket,
        "artist": album.get("artist") or album.get("artist_name"),
        "title": album.get("title") or album.get("sample_title"),
        "master_id": album.get("master_id"),
        "main_release_id": album.get("main_release_id"),
        "artist_id": album.get("artist_id"),
        "year": album.get("year"),
        "already_in_catalog": already_in_catalog,
    }
    if bucket == "graph_rich":
        base["marginal_new_edges"] = album.get("marginal_new_edges")
        base["marginal_new_contributors"] = album.get("marginal_new_contributors")
        base["score"] = album.get("score")
    if bucket == "coverage_gap":
        base["gap_dimension"] = album.get("gap_dimension")
        base["gap_bucket"] = album.get("gap_bucket")
        base["gap_rationale"] = album.get("gap_rationale")
    return base


def _agreed_snapshot_date(sources: dict[str, dict[str, Any]]) -> str:
    """Every source must carry the SAME non-empty `snapshot_date`, or this
    raises rather than silently assembling a packet that mixes generations.

    Real risk this guards against: combining a current catalog or personal
    seed with a stale graph-rich selection would produce an apparently
    coherent packet whose marginal scores and resolved identities actually
    describe a different Discogs dump than the catalog under review --
    exactly the class of mistake `build-public-album-catalog`'s own
    multi-input snapshot cross-check exists to prevent, applied here to a
    pre-decision review packet instead of the publication step itself.
    """
    snapshot_dates = {
        name: str(payload.get("snapshot_date") or "") for name, payload in sources.items()
    }
    missing = sorted(name for name, sd in snapshot_dates.items() if not sd)
    if missing:
        raise ValueError(
            f"missing snapshot_date on expansion-review input(s): {missing} -- "
            "unknown snapshot metadata is refused just like a mismatched one"
        )
    agreed = next(iter(snapshot_dates.values()))
    mismatched = {name: sd for name, sd in snapshot_dates.items() if sd != agreed}
    if mismatched:
        raise ValueError(
            f"mismatched snapshot_date across expansion-review inputs: {snapshot_dates} -- "
            "refusing to assemble a packet that mixes generations"
        )
    return agreed


def build_expansion_review_packet(
    *,
    generated_at: str,
    current_catalog: dict[str, Any],
    personal_seed: dict[str, Any],
    graph_rich_selection: dict[str, Any],
    coverage_gap: dict[str, Any],
) -> dict[str, Any]:
    """Build the combined review packet.

    `current_catalog` is `apps/web/public/data/catalog/albums.v1.json`'s
    shape; `personal_seed` is `data/albums/editorial-seed-v1.json`'s shape
    (Bucket A); `graph_rich_selection` is `select-graph-rich-candidates`'s
    output shape (Bucket B); `coverage_gap` is `{"snapshot_date": ...,
    "candidates": [...]}`, each candidate an already-resolved album dict
    carrying `gap_dimension`/`gap_bucket`/`gap_rationale` -- this function
    combines and annotates, it does not choose Bucket C's picks itself
    (that is a real editorial judgment call, made the same way Bucket A's
    was: resolved against the real snapshot, then reviewed here).

    All four inputs must carry the same non-empty `snapshot_date`; a
    mismatch or omission raises rather than silently mixing generations
    (see `_agreed_snapshot_date`). The agreed value is recorded on the
    returned packet.
    """
    agreed_snapshot_date = _agreed_snapshot_date(
        {
            "current_catalog": current_catalog,
            "personal_seed": personal_seed,
            "graph_rich_selection": graph_rich_selection,
            "coverage_gap": coverage_gap,
        }
    )
    coverage_gap_candidates = coverage_gap.get("candidates", [])

    current_master_ids = {
        int(a["master_id"])
        for a in current_catalog.get("albums", [])
        if a.get("master_id") is not None
    }

    def already_in(album: dict[str, Any]) -> bool:
        master_id = album.get("master_id")
        return master_id is not None and int(master_id) in current_master_ids

    personal = [_entry("personal", a, already_in(a)) for a in personal_seed.get("albums", [])]
    graph_rich = [
        _entry("graph_rich", a, already_in(a)) for a in graph_rich_selection.get("selected", [])
    ]
    coverage_gap_entries = [
        _entry("coverage_gap", a, already_in(a)) for a in coverage_gap_candidates
    ]
    entries = personal + graph_rich + coverage_gap_entries

    master_ids_seen: dict[int, list[str]] = {}
    for entry in entries:
        master_id = entry.get("master_id")
        if master_id is None:
            continue
        master_ids_seen.setdefault(int(master_id), []).append(entry["bucket"])
    warnings = [
        f"master_id {master_id} appears in more than one bucket: {', '.join(buckets)}"
        for master_id, buckets in sorted(master_ids_seen.items())
        if len(buckets) > 1
    ]
    warnings.extend(
        f"master_id {entry['master_id']} ({entry['bucket']}) is already in the published catalog"
        for entry in entries
        if entry["already_in_catalog"]
    )

    return {
        "schema_version": EXPANSION_REVIEW_SCHEMA_VERSION,
        "generated_at": generated_at,
        "snapshot_date": agreed_snapshot_date,
        "current_catalog_count": len(current_catalog.get("albums", [])),
        "proposed_addition_count": len(entries),
        "proposed_total_count": len(current_catalog.get("albums", [])) + len(entries),
        "bucket_counts": {
            "personal": len(personal),
            "graph_rich": len(graph_rich),
            "coverage_gap": len(coverage_gap_entries),
        },
        "warnings": warnings,
        "entries": entries,
    }
