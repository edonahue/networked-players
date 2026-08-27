"""Tests for the public editorial seed -- the working-set extension that lets
a public album be resolved and published without depending on the private,
collection-seeded one-hop corpus reaching it (Phase 7). See
data/contracts/editorial-seed-v1.md."""

from __future__ import annotations

from pathlib import Path

from networked_players_graph_core.editorial_seed import (
    EDITORIAL_SEED_KIND,
    EDITORIAL_SEED_SCHEMA_VERSION,
    editorial_seed_failures,
    editorial_seed_release_ids,
    resolve_editorial_albums,
)
from networked_players_graph_core.graph import CreditGraph


def test_resolves_by_exact_title_artist_text_match(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        result = resolve_editorial_albums(graph, [{"artist": "Cara", "title": "Third Wave"}])
    assert result["unresolved"] == []
    assert len(result["resolved"]) == 1
    album = result["resolved"][0]
    assert album["master_id"] == 903
    assert album["main_release_id"] == 3
    assert album["artist_id"] == 300
    assert album["artist"] == "Cara"
    assert album["year"] == 1995


def test_resolves_by_master_id_hint_sidestepping_title_text(dataset_root: Path) -> None:
    """A pinned master_id resolves without touching the title string at all --
    the sidestep that matters for a real Discogs punctuation mismatch like
    curly vs. straight quotes in `Sign "O" The Times`."""
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        result = resolve_editorial_albums(
            graph,
            [{"artist": "Cara", "title": "some completely different text", "master_id": 903}],
        )
    assert result["unresolved"] == []
    assert result["resolved"][0]["main_release_id"] == 3


def test_unresolved_when_nothing_matches(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        result = resolve_editorial_albums(graph, [{"artist": "Nobody", "title": "Nothing"}])
    assert result["resolved"] == []
    assert result["unresolved"] == [
        {
            "artist": "Nobody",
            "title": "Nothing",
            "reason": "no matching release in this snapshot",
        }
    ]


def test_a_query_needs_master_id_or_both_artist_and_title(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        result = resolve_editorial_albums(graph, [{"artist": "Cara"}])
    assert result["resolved"] == []
    assert "master_id, or both artist and title" in result["unresolved"][0]["reason"]


def test_duplicate_master_id_keeps_the_first_and_rejects_the_second(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        result = resolve_editorial_albums(
            graph,
            [
                {"artist": "Cara", "title": "Third Wave"},
                {"artist": "Cara", "title": "Third Wave", "master_id": 903},
            ],
        )
    assert len(result["resolved"]) == 1
    assert "duplicate" in result["unresolved"][0]["reason"]
    assert result["unresolved"][0]["master_id"] == 903


def test_curated_exclusion_rejects_the_album(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        result = resolve_editorial_albums(
            graph,
            [{"artist": "Cara", "title": "Third Wave"}],
            master_exclusions=frozenset({903}),
        )
    assert result["resolved"] == []
    assert "curated" in result["unresolved"][0]["reason"]
    assert result["unresolved"][0]["eligibility"]["curated_exclusion"] is True


def test_non_studio_genre_gate_rejects_the_album_when_masters_attached(
    dataset_root: Path, tmp_path: Path
) -> None:
    from conftest import SNAPSHOT_DATE, write_synthetic_masters

    masters_root = write_synthetic_masters(
        tmp_path / "masters",
        master_rows=[
            {
                "snapshot_date": SNAPSHOT_DATE,
                "master_id": 903,
                "main_release_id": 3,
                "title": "Third Wave",
                "year": 1995,
                "genres": ["Stage & Screen"],
                "styles": [],
                "data_quality": None,
                "source_url": "https://example.invalid/master/903",
            }
        ],
    )
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        graph.attach_masters(masters_root)
        result = resolve_editorial_albums(graph, [{"artist": "Cara", "title": "Third Wave"}])
    assert result["resolved"] == []
    assert "non-studio" in result["unresolved"][0]["reason"]


def test_format_gate_is_reported_unchecked_never_silently_passed(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        result = resolve_editorial_albums(graph, [{"artist": "Cara", "title": "Third Wave"}])
    assert "not checked" in result["resolved"][0]["eligibility"]["release_format_gate"]


def test_genre_style_gate_reported_unchecked_without_masters_root(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        result = resolve_editorial_albums(graph, [{"artist": "Cara", "title": "Third Wave"}])
    assert "not checked" in result["resolved"][0]["eligibility"]["genre_style_gate"]


def test_masters_attached_overrides_title_and_year(dataset_root: Path, masters_root: Path) -> None:
    with CreditGraph.open(dataset_root, build_edges=False) as graph:
        graph.attach_masters(masters_root)
        result = resolve_editorial_albums(graph, [{"artist": "Alice", "title": "First Light"}])
    assert result["resolved"][0]["title"] == "First Light (Deluxe)"
    assert result["resolved"][0]["year"] == 1995
    assert "genre_style_gate" not in result["resolved"][0]["eligibility"]


def test_editorial_seed_release_ids_dedupes_and_sorts() -> None:
    payload = {
        "albums": [
            {"main_release_id": 300},
            {"main_release_id": 100},
            {"main_release_id": 300},
        ]
    }
    assert editorial_seed_release_ids(payload) == [100, 300]


def _valid_payload() -> dict:
    return {
        "schema_version": EDITORIAL_SEED_SCHEMA_VERSION,
        "kind": EDITORIAL_SEED_KIND,
        "snapshot_date": "20260601",
        "generated_by": "networked-players-catalog resolve-editorial-albums 0.1.0",
        "generated_at": "2026-08-27T00:00:00+00:00",
        "note": "",
        "albums": [
            {
                "query_artist": "Cara",
                "query_title": "Third Wave",
                "master_id": 903,
                "main_release_id": 3,
                "artist_id": 300,
                "artist": "Cara",
                "title": "Third Wave",
                "year": 1995,
            }
        ],
    }


def test_editorial_seed_failures_accepts_a_well_formed_payload() -> None:
    assert editorial_seed_failures(_valid_payload()) == []


def test_editorial_seed_failures_rejects_a_leaked_eligibility_key() -> None:
    payload = _valid_payload()
    payload["albums"][0]["eligibility"] = {"curated_exclusion": False}
    failures = editorial_seed_failures(payload)
    assert any("unexpected keys" in f for f in failures)


def test_editorial_seed_failures_rejects_wrong_kind() -> None:
    payload = _valid_payload()
    payload["kind"] = "private-collection-seed"
    assert any("kind" in f for f in editorial_seed_failures(payload))


def test_editorial_seed_failures_rejects_a_duplicate_master_id() -> None:
    payload = _valid_payload()
    payload["albums"].append(dict(payload["albums"][0]))
    assert any("duplicate" in f for f in editorial_seed_failures(payload))


def test_editorial_seed_failures_rejects_forbidden_substrings() -> None:
    payload = _valid_payload()
    payload["note"] = "resolved from local/research/catalog-expansion notes"
    assert any("forbidden substring" in f for f in editorial_seed_failures(payload))
