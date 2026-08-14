"""Which release is chosen to EVIDENCE a co-credit pair (ADR 0059).

The pair set is fixed by the edge rules in `credit_edges_sql`; only the
representative release moves. These tests hold that line explicitly,
because an ordering change that silently added or dropped an edge would be
a data-correctness bug wearing a presentation-change costume.

Every fixture is synthetic and written through the real Parquet schemas,
so the SQL is exercised against DuckDB rather than string-matched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import (  # type: ignore[import-not-found]
    SNAPSHOT_DATE,
    _performed,
    _release,
    write_synthetic_dataset,
)
from networked_players_graph_core.graph import (
    EVIDENCE_CAVEAT_DESCRIPTORS,
    EVIDENCE_CAVEAT_TIERS,
    CreditGraph,
    EvidenceReleasePreference,
    credit_edges_sql,
)


def _format_row(release_id: int, descriptions: list[str]) -> dict[str, Any]:
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "release_id": release_id,
        "format_index": 0,
        "format_name": "Vinyl",
        "quantity": 1,
        "format_text": None,
        "descriptions": descriptions,
    }


def _pair_dataset(
    root: Path,
    *,
    releases: list[dict[str, Any]],
    format_rows: list[dict[str, Any]] | None,
) -> Path:
    """Two artists co-credited on EVERY supplied release.

    That is the situation the preference exists for: one pair, many
    candidate releases, and today's `min(release_id)` picking whichever was
    catalogued first.
    """
    credits: list[dict[str, Any]] = []
    for release in releases:
        rid = int(release["release_id"])
        credits += _performed(rid, artist_id=1, name="Ann")
        credits += _performed(rid, artist_id=2, name="Bo")
    return write_synthetic_dataset(
        root,
        release_rows=releases,
        credit_rows=credits,
        release_format_rows=format_rows,
    )


def _evidence_for_pair(root: Path, preference: EvidenceReleasePreference | None) -> int:
    with CreditGraph.open(root, evidence_release_preference=preference) as graph:
        rows = graph._connection.execute(
            "SELECT release_id FROM credit_edges WHERE artist_a_id = 1 AND artist_b_id = 2"
        ).fetchall()
    assert len(rows) == 1, f"expected exactly one representative, got {rows}"
    return int(rows[0][0])


def test_no_preference_is_byte_identical_to_the_historical_sql() -> None:
    """The parameter is opt-in in the strongest sense available: with it
    unset the generated SQL is character-for-character what every existing
    caller has always run. This is what makes it safe to ship the option
    without re-validating challenge, record routes and cohort
    connectivity."""
    assert credit_edges_sql(max_artists_per_release=50) == credit_edges_sql(
        max_artists_per_release=50, evidence_release_preference=None
    )
    assert "min(release_id) AS release_id" in credit_edges_sql(max_artists_per_release=50)


def test_default_collapse_picks_the_lowest_release_id(tmp_path: Path) -> None:
    """The behaviour being replaced, pinned so the replacement is a
    demonstrated change rather than an asserted one."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[
            _release(900, "Record High", master_id=5, master_is_main_release=True),
            _release(100, "Record Low"),
        ],
        format_rows=[_format_row(900, ["Album"]), _format_row(100, ["Unofficial Release"])],
    )
    assert _evidence_for_pair(root, None) == 100


def test_preferred_release_ids_outrank_a_lower_id(tmp_path: Path) -> None:
    """Tier 1: an album the catalog itself names is the most defensible
    evidence a route can show, and it wins even though its Discogs id is
    an order of magnitude higher."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[_release(900, "Record High"), _release(100, "Record Low")],
        format_rows=[_format_row(900, ["Album"]), _format_row(100, ["Single"])],
    )
    preference = EvidenceReleasePreference(preferred_release_ids=(900,))
    assert _evidence_for_pair(root, preference) == 900


@pytest.mark.parametrize("descriptor", EVIDENCE_CAVEAT_DESCRIPTORS)
def test_each_caveat_descriptor_de_prefers_a_lower_id(tmp_path: Path, descriptor: str) -> None:
    """Tier 2, once per descriptor so a future edit to the tuple cannot
    quietly disable one. Note what is NOT asserted: the winner is not
    claimed to be a studio album, only to carry no caveat."""
    root = _pair_dataset(
        tmp_path / f"ds-{descriptor.replace(' ', '-')}",
        releases=[_release(900, "Record High"), _release(100, "Record Low")],
        format_rows=[_format_row(900, ["Album"]), _format_row(100, [descriptor])],
    )
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 900


def test_master_main_release_breaks_a_tie_between_uncaveated_releases(tmp_path: Path) -> None:
    """Tier 3 only decides once tiers 1 and 2 are level."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[
            _release(900, "Record High", master_id=5, master_is_main_release=True),
            _release(100, "Record Low", master_id=5, master_is_main_release=False),
        ],
        format_rows=[_format_row(900, ["Album"]), _format_row(100, ["Album"])],
    )
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 900


def test_release_id_remains_the_final_deterministic_tiebreak(tmp_path: Path) -> None:
    """With every signal level the result must still be total and stable --
    otherwise two builds of the same dataset could disagree."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[_release(900, "Record High"), _release(100, "Record Low")],
        format_rows=[_format_row(900, ["Album"]), _format_row(100, ["Album"])],
    )
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 100


def test_all_candidates_caveated_still_yields_a_representative(tmp_path: Path) -> None:
    """A pair with nothing but caveated evidence does not lose its edge.
    The preference ranks; it never filters -- and it still ranks WITHIN the
    caveats, so the compilation beats the bootleg rather than the two
    tying and falling through to the release-id tiebreak."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[_release(900, "Record High"), _release(100, "Record Low")],
        format_rows=[_format_row(900, ["Compilation"]), _format_row(100, ["Unofficial Release"])],
    )
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 900


def test_the_edge_set_is_identical_with_and_without_a_preference(tmp_path: Path) -> None:
    """The invariant the whole change rests on. Three artists across four
    releases, including a release that only one of them appears on, so the
    pair set is non-trivial."""
    releases = [
        _release(900, "Record High", master_id=5, master_is_main_release=True),
        _release(300, "Record Mid"),
        _release(100, "Record Low"),
        _release(50, "Record Solo"),
    ]
    credits: list[dict[str, Any]] = []
    for rid in (900, 300, 100):
        credits += _performed(rid, artist_id=1, name="Ann")
        credits += _performed(rid, artist_id=2, name="Bo")
        credits += _performed(rid, artist_id=3, name="Cy")
    credits += _performed(50, artist_id=1, name="Ann")
    root = write_synthetic_dataset(
        tmp_path / "ds",
        release_rows=releases,
        credit_rows=credits,
        release_format_rows=[
            _format_row(900, ["Album"]),
            _format_row(300, ["Compilation"]),
            _format_row(100, ["Unofficial Release"]),
            _format_row(50, ["Album"]),
        ],
    )

    def pairs(preference: EvidenceReleasePreference | None) -> set[tuple[int, int]]:
        with CreditGraph.open(root, evidence_release_preference=preference) as graph:
            return {
                (int(a), int(b))
                for a, b in graph._connection.execute(
                    "SELECT artist_a_id, artist_b_id FROM credit_edges"
                ).fetchall()
            }

    baseline = pairs(None)
    assert baseline == pairs(EvidenceReleasePreference(preferred_release_ids=(900,)))
    assert (1, 2) in baseline and (2, 3) in baseline


def test_a_dataset_without_release_formats_still_builds(tmp_path: Path) -> None:
    """Pre-v3 datasets have no `table=release_formats` directory at all.
    The caveat tier must go quiet rather than raise -- so tier 3 decides
    here even though the fixture would otherwise be a caveat case."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[
            _release(900, "Record High", master_id=5, master_is_main_release=True),
            _release(100, "Record Low", master_id=5, master_is_main_release=False),
        ],
        format_rows=None,
    )
    assert not (root / "table=release_formats").exists()
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 900


def test_a_descriptor_containing_an_apostrophe_is_escaped(tmp_path: Path) -> None:
    """The descriptors are constants today, but they are source text and
    the SQL builds a literal list from them."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[_release(900, "Record High"), _release(100, "Record Low")],
        format_rows=[_format_row(900, ["Album"]), _format_row(100, ["DJ's Own"])],
    )
    preference = EvidenceReleasePreference(caveat_tiers=(("DJ's Own",),))
    assert _evidence_for_pair(root, preference) == 900


def test_a_bootleg_loses_to_a_reissue(tmp_path: Path) -> None:
    """Severity ordering, and the reason it exists. A single combined
    "has any caveat" term ranks these two equally and lets the release-id
    tiebreak choose -- which on the real corpus traded 5,178
    reissue-evidenced edges away while taking on 74 more unofficial ones.
    An unofficial release is the mashup/bootleg case ADR 0059 opens with;
    a reissue is a real collaboration on a secondary artefact."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[_release(900, "Record High"), _release(100, "Record Low")],
        format_rows=[
            _format_row(900, ["Reissue"]),
            _format_row(100, ["Unofficial Release"]),
        ],
    )
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 900


def test_a_container_loses_to_a_pressing_caveat(tmp_path: Path) -> None:
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[_release(900, "Record High"), _release(100, "Record Low")],
        format_rows=[_format_row(900, ["Promo"]), _format_row(100, ["Compilation"])],
    )
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 900


def test_a_bootleg_loses_to_a_container(tmp_path: Path) -> None:
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[_release(900, "Record High"), _release(100, "Record Low")],
        format_rows=[
            _format_row(900, ["Compilation"]),
            _format_row(100, ["Unofficial Release"]),
        ],
    )
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 900


def test_severity_tiers_are_disjoint_and_cover_every_descriptor() -> None:
    """The flattened tuple is derived from the tiers, so a descriptor
    added to one without the other cannot silently go unranked."""
    flat = [d for tier in EVIDENCE_CAVEAT_TIERS for d in tier]
    assert len(flat) == len(set(flat)), "a descriptor appears in two severity tiers"
    assert set(flat) == set(EVIDENCE_CAVEAT_DESCRIPTORS)


def test_the_ranking_and_the_published_flags_share_one_vocabulary() -> None:
    """`EVIDENCE_CAVEAT_TIERS` (graph-core, decides which release EVIDENCES
    a pair) and `CAVEAT_FLAG_DESCRIPTORS` (contracts, decides what the
    registry PUBLISHES) are separate literals in separate packages. Add a
    descriptor to one only and the two artifacts silently disagree: either
    the graph de-prefers a release the registry cannot flag -- so PR 5
    renders it as uncaveated -- or the registry flags one the ranker never
    de-preferred. Nothing else binds them, so this does."""
    from networked_players_contracts.evidence_release_registry import CAVEAT_FLAG_DESCRIPTORS

    published = {d for _, descriptors in CAVEAT_FLAG_DESCRIPTORS for d in descriptors}
    assert set(EVIDENCE_CAVEAT_DESCRIPTORS) == published


def test_an_empty_release_formats_directory_degrades_like_a_missing_one(tmp_path: Path) -> None:
    """A partial dataset copy leaves the directory present but empty.
    `read_parquet` raises on a glob matching nothing, which the open path
    would otherwise turn into a bare "could not open dataset" and hard-fail
    EVERY consumer -- including the ones that never read format
    descriptors."""
    root = _pair_dataset(
        tmp_path / "ds",
        releases=[
            _release(900, "Record High", master_id=5, master_is_main_release=True),
            _release(100, "Record Low", master_id=5, master_is_main_release=False),
        ],
        format_rows=[],
    )
    for stale in (root / "table=release_formats").glob("*.parquet"):
        stale.unlink()
    assert (root / "table=release_formats").is_dir()
    assert not list((root / "table=release_formats").glob("*.parquet"))
    # Opens at all (the real regression), and the caveat tier goes quiet so
    # tier 3 decides.
    assert _evidence_for_pair(root, EvidenceReleasePreference()) == 900
