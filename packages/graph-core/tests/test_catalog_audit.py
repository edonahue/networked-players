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
        expected = "editorial" if album_id in editorial_ids else "generic_candidate"
        assert row["selection_source"] == expected


def test_audit_marks_pre_resolved_as_personal_editorial_not_graph_candidate(
    dataset_root: Path, masters_root: Path
) -> None:
    """Real regression: build_album_catalog_audit classifies purely by list
    POSITION against editorial_count. Before this test existed to prove it,
    a Bucket A (pre-resolved) album -- inserted right after the editorial
    segment in assemble_album_catalog's own albums list -- would land at an
    index >= editorial_count and be silently mislabeled graph_candidate."""
    editorial = [{"artist": "Alice", "title": "First Light"}]
    pre_resolved = [
        {
            "query_artist": "Fictoquai",
            "query_title": "Personal Pick",
            "master_id": None,
            "main_release_id": 3,
            "artist_id": 700,
            "artist": "Fictoquai",
            "title": "Personal Pick",
            "year": 1999,
        }
    ]
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        candidates = rank_album_candidates(dataset_root)
        catalog = assemble_album_catalog(
            graph,
            editorial,
            candidates,
            target_count=4,
            pre_resolved_albums=pre_resolved,
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test",
        )
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    by_id = {row["album_id"]: row for row in audit["albums"]}
    fictoquai_id = next(a["id"] for a in catalog["albums"] if a["artist"] == "Fictoquai")
    assert by_id[fictoquai_id]["selection_source"] == "editorial"
    # ADR 0069: public label, never "personal_editorial".
    # The editorial and graph-candidate segments are still classified
    # correctly around the inserted personal_editorial segment.
    alice_id = next(a["id"] for a in catalog["albums"] if a["artist"] == "Alice")
    assert by_id[alice_id]["selection_source"] == "editorial"
    other_ids = {a["id"] for a in catalog["albums"] if a["artist"] not in ("Alice", "Fictoquai")}
    assert all(by_id[aid]["selection_source"] == "generic_candidate" for aid in other_ids)


def test_audit_distinguishes_graph_rich_and_coverage_gap_from_personal_editorial(
    dataset_root: Path, masters_root: Path
) -> None:
    """Phase 7 Buckets B/C: `pre_resolved_buckets` lets the audit tell a
    graph-rich pick and a coverage-gap pick apart from a personal/editorial
    one and from each other, instead of collapsing every pre-resolved album
    into a single `personal_editorial` label."""
    editorial = [{"artist": "Alice", "title": "First Light"}]
    personal = [
        {
            "query_artist": "Fictoquai",
            "query_title": "Personal Pick",
            "master_id": None,
            "main_release_id": 3,
            "artist_id": 700,
            "artist": "Fictoquai",
            "title": "Personal Pick",
            "year": 1999,
        }
    ]
    graph_rich = [
        {
            "master_id": None,
            "main_release_id": 9501,
            "artist_id": 750,
            "artist": "Graph Rich Artist",
            "title": "Graph Rich Pick",
            "year": 2001,
        }
    ]
    coverage_gap = [
        {
            "master_id": None,
            "main_release_id": 9601,
            "artist_id": 760,
            "artist": "Coverage Gap Artist",
            "title": "Coverage Gap Pick",
            "year": 2002,
        }
    ]
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        catalog = assemble_album_catalog(
            graph,
            editorial,
            [],
            target_count=10,
            pre_resolved_albums=personal,
            additional_pre_resolved=[
                ("graph_rich", graph_rich, True),
                ("coverage_gap", coverage_gap, True),
            ],
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test",
        )
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    by_artist = {row["artist"]: row["selection_source"] for row in audit["albums"]}
    assert by_artist["Alice"] == "editorial"
    assert by_artist["Fictoquai"] == "editorial"  # ADR 0069: never "personal_editorial"
    assert by_artist["Graph Rich Artist"] == "graph_rich"
    assert by_artist["Coverage Gap Artist"] == "coverage_gap"


def test_audit_falls_back_to_personal_editorial_for_a_catalog_without_pre_resolved_buckets(
    dataset_root: Path, masters_root: Path
) -> None:
    """A catalog built before `pre_resolved_buckets` existed (real committed
    catalogs so far, and any fixture predating this change) has only the
    flat `pre_resolved_count` field. `build_album_catalog_audit` must
    classify it exactly as it always did -- one contiguous
    `personal_editorial` range -- not treat the missing field as zero
    pre-resolved albums."""
    catalog = _catalog(dataset_root, masters_root)
    del catalog["pre_resolved_buckets"]  # simulate a pre-existing-field catalog
    catalog["pre_resolved_count"] = 1
    # Reorder nothing -- just claim the first candidate-segment album is
    # actually a pre-resolved one, matching the old flat-count contract.
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    by_id = {row["album_id"]: row for row in audit["albums"]}
    pre_resolved_id = catalog["albums"][catalog["editorial_count"]]["id"]
    assert by_id[pre_resolved_id]["selection_source"] == "editorial"
    # ADR 0069: public label, never "personal_editorial".


def test_audit_prefers_a_v2_albums_own_selection_source_field(
    dataset_root: Path, masters_root: Path
) -> None:
    """ADR 0069, field-first: when an album already carries its own
    selection_source (a v2 catalog), the audit uses it directly instead of
    re-deriving it positionally -- proven here by a deliberately WRONG
    positional setup (empty pre_resolved_buckets/editorial_count) that would
    mislabel everything "generic_candidate" if the field weren't consulted."""
    catalog = _catalog(dataset_root, masters_root)
    for album in catalog["albums"]:
        album["selection_source"] = "coverage_gap"
    catalog["editorial_count"] = 0
    catalog["pre_resolved_buckets"] = []
    catalog["pre_resolved_count"] = 0
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        audit = build_album_catalog_audit(
            graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
    assert all(row["selection_source"] == "coverage_gap" for row in audit["albums"])


def test_audit_transition_v1_and_v2_agree_on_the_same_real_catalog(
    dataset_root: Path, masters_root: Path
) -> None:
    """Transition assertion (graph-expansion Phase 0 slice 0-B): the
    field-first refactor must be a genuine no-op for existing (v1) data.
    Builds the SAME underlying picks two ways -- once as today's v1 shape
    (no per-album selection_source, purely positional) and once tagged with
    the real v2 selection_source `assemble_album_catalog` would have
    produced for the identical picks -- and proves the audit's
    selection_source assignment, and its per-label counts, are identical
    either way."""
    editorial = [{"artist": "Alice", "title": "First Light"}]
    personal = [
        {
            "query_artist": "Fictoquai",
            "query_title": "Personal Pick",
            "master_id": None,
            "main_release_id": 3,
            "artist_id": 700,
            "artist": "Fictoquai",
            "title": "Personal Pick",
            "year": 1999,
        }
    ]
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        candidates = rank_album_candidates(dataset_root)
        v1_catalog = assemble_album_catalog(
            graph,
            editorial,
            candidates,
            target_count=4,
            pre_resolved_albums=personal,
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test",
        )
        v2_catalog = assemble_album_catalog(
            graph,
            editorial,
            candidates,
            target_count=4,
            pre_resolved_albums=personal,
            snapshot_date=SNAPSHOT_DATE,
            generated_by="test",
            featured_master_ids=frozenset(),
        )
        v1_audit = build_album_catalog_audit(
            graph, v1_catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )
        v2_audit = build_album_catalog_audit(
            graph, v2_catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
        )

    def _sources_by_artist(audit: dict) -> dict[str, str]:
        return {row["artist"]: row["selection_source"] for row in audit["albums"]}

    assert _sources_by_artist(v1_audit) == _sources_by_artist(v2_audit)

    def _counts_by_label(audit: dict) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in audit["albums"]:
            counts[row["selection_source"]] = counts.get(row["selection_source"], 0) + 1
        return counts

    assert _counts_by_label(v1_audit) == _counts_by_label(v2_audit)


def test_audit_rejects_a_negative_bucket_count(dataset_root: Path, masters_root: Path) -> None:
    """Real Codex finding: a stale or hand-edited `pre_resolved_buckets`
    entry must be rejected before it's used to derive positional
    provenance ranges, not trusted silently."""
    catalog = _catalog(dataset_root, masters_root)
    catalog["pre_resolved_count"] = -1
    catalog["pre_resolved_buckets"] = [{"label": "graph_rich", "count": -1}]
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        with pytest.raises(AlbumCatalogAuditError, match="non-negative-integer"):
            build_album_catalog_audit(
                graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
            )


def test_audit_rejects_bucket_counts_not_summing_to_pre_resolved_count(
    dataset_root: Path, masters_root: Path
) -> None:
    catalog = _catalog(dataset_root, masters_root)
    catalog["pre_resolved_count"] = 5
    catalog["pre_resolved_buckets"] = [{"label": "graph_rich", "count": 1}]
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        with pytest.raises(AlbumCatalogAuditError, match="counts sum to"):
            build_album_catalog_audit(
                graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
            )


def test_audit_rejects_bucket_totals_overrunning_the_album_list(
    dataset_root: Path, masters_root: Path
) -> None:
    catalog = _catalog(dataset_root, masters_root)
    huge_count = len(catalog["albums"]) * 10
    catalog["pre_resolved_count"] = huge_count
    catalog["pre_resolved_buckets"] = [{"label": "graph_rich", "count": huge_count}]
    with CreditGraph.open(dataset_root) as graph:
        graph.attach_masters(masters_root)
        with pytest.raises(AlbumCatalogAuditError, match="exceeds the catalog's own album count"):
            build_album_catalog_audit(
                graph, catalog, allowed_release_ids=frozenset(), master_exclusions=frozenset()
            )


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
