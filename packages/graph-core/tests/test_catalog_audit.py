from __future__ import annotations

from pathlib import Path

import pytest

from networked_players_graph_core.analysis import assemble_album_catalog, rank_album_candidates
from networked_players_graph_core.catalog_audit import (
    AlbumCatalogAuditError,
    build_album_catalog_audit,
    validate_album_catalog_audit,
)
from networked_players_graph_core.graph import CreditGraph

SNAPSHOT_DATE = "20260601"


def _catalog(dataset_root: Path, masters_root: Path) -> dict:
    editorial = [{"artist": "Alice", "title": "First Light"}]
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        candidates = rank_album_candidates(dataset_root)
        return assemble_album_catalog(
            graph,
            editorial,
            candidates,
            target_count=3,
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test",
        )


def test_audit_has_exactly_one_row_per_catalog_album(
    dataset_root: Path, masters_root: Path
) -> None:
    catalog = _catalog(dataset_root, masters_root)
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    assert len(audit["albums"]) == len(catalog["albums"])
    assert {row["album_id"] for row in audit["albums"]} == {a["id"] for a in catalog["albums"]}
    validate_album_catalog_audit(catalog, audit)  # does not raise


def test_audit_marks_editorial_vs_graph_candidate_selection_source(
    dataset_root: Path, masters_root: Path
) -> None:
    catalog = _catalog(dataset_root, masters_root)
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    by_id = {row["album_id"]: row for row in audit["albums"]}
    editorial_ids = {a["id"] for a in catalog["albums"][: catalog["editorial_count"]]}
    for album_id, row in by_id.items():
        expected = "editorial" if album_id in editorial_ids else "graph_candidate"
        assert row["selection_source"] == expected


def test_audit_records_master_genre_style_and_release_format_results(
    dataset_root: Path, masters_root: Path
) -> None:
    catalog = _catalog(dataset_root, masters_root)
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        # Only release 1 (master 901, Alice's "First Light") is allowed.
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset({1}), master_exclusions=frozenset()
        )
    by_id = {row["album_id"]: row for row in audit["albums"]}
    first_light = next(row for row in by_id.values() if "First Light" in row["title"])
    assert first_light["release_format_policy_result"] == "allowed"
    assert first_light["master_genre_style_result"] == "studio_signal_clean"
    others = [row for row in by_id.values() if "First Light" not in row["title"]]
    assert others  # sanity: there really are other rows to check
    assert all(row["release_format_policy_result"] == "excluded" for row in others)


def test_audit_flags_a_various_artists_credit() -> None:
    catalog = {
        "catalog_version": "test-v1",
        "snapshot_date": SNAPSHOT_DATE,
        "editorial_count": 0,
        "albums": [
            {
                "id": "master-1",
                "master_id": None,
                "artist": "Various Artists",
                "title": "Now That's What I Call Music",
                "year": 1990,
                "main_release_id": 1,
                "artist_id": 1,
            }
        ],
    }

    class _NoMastersGraph:
        def master(self, master_id: int) -> None:
            return None

    audit = build_album_catalog_audit(
        _NoMastersGraph(),  # type: ignore[arg-type]
        catalog,
        allowed_release_ids=frozenset({1}),
        master_exclusions=frozenset(),
    )
    assert audit["albums"][0]["automated_flags"] == ["various_artists_credit"]


def test_audit_flags_a_title_pattern_match() -> None:
    catalog = {
        "catalog_version": "test-v1",
        "snapshot_date": SNAPSHOT_DATE,
        "editorial_count": 0,
        "albums": [
            {
                "id": "master-2",
                "master_id": None,
                "artist": "Neil Diamond",
                "title": "Hot August Night (Live)",
                "year": 1972,
                "main_release_id": 2,
                "artist_id": 2,
            }
        ],
    }

    class _NoMastersGraph:
        def master(self, master_id: int) -> None:
            return None

    audit = build_album_catalog_audit(
        _NoMastersGraph(),  # type: ignore[arg-type]
        catalog,
        allowed_release_ids=frozenset({2}),
        master_exclusions=frozenset(),
    )
    assert "title_pattern_match" in audit["albums"][0]["automated_flags"]


def test_validate_rejects_missing_audit_row(dataset_root: Path, masters_root: Path) -> None:
    catalog = _catalog(dataset_root, masters_root)
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    audit["albums"].pop()
    with pytest.raises(AlbumCatalogAuditError, match="no audit row"):
        validate_album_catalog_audit(catalog, audit)


def test_validate_rejects_extra_audit_row_not_in_catalog(
    dataset_root: Path, masters_root: Path
) -> None:
    catalog = _catalog(dataset_root, masters_root)
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    audit["albums"].append(dict(audit["albums"][0], album_id="not-in-catalog"))
    with pytest.raises(AlbumCatalogAuditError, match="not in the catalog"):
        validate_album_catalog_audit(catalog, audit)


def test_validate_rejects_stale_catalog_version(dataset_root: Path, masters_root: Path) -> None:
    catalog = _catalog(dataset_root, masters_root)
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    audit["catalog_version"] = "stale-version"
    with pytest.raises(AlbumCatalogAuditError, match="stale audit"):
        validate_album_catalog_audit(catalog, audit)


def test_validate_rejects_an_excluded_row_that_is_still_in_the_catalog(
    dataset_root: Path, masters_root: Path
) -> None:
    catalog = _catalog(dataset_root, masters_root)
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    audit["albums"][0]["final_eligibility"] = "excluded"
    audit["albums"][0]["exclusion_reason"] = "test exclusion"
    with pytest.raises(AlbumCatalogAuditError, match="must never ship"):
        validate_album_catalog_audit(catalog, audit)
