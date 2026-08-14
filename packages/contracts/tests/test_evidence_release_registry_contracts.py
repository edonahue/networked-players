from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.evidence_release_registry import (
    CAVEAT_FLAG_NAMES,
    caveat_flags_for_descriptors,
    evidence_release_registry_failures,
    evidence_release_registry_version,
)

_SNAPSHOT = "20260601"


def _catalog() -> dict[str, Any]:
    albums = [
        {
            "id": "master-1",
            "master_id": None,
            "main_release_id": 1,
            "title": "First Light",
            "artist_id": 100,
            "artist": "Alice",
            "year": 1995,
        }
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT),
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-album-catalog 0.1.0",
        "albums": albums,
    }


def _base_fields() -> dict[str, Any]:
    return {
        "release_ids": [1, 2],
        "titles": ["First Light", "Other Release"],
        "years": [1995, None],
        "countries": ["US", None],
        "master_ids": [1, None],
        "source_urls": ["https://data.discogs.com/?download=fake"] * 2,
        "cover_uri150s": ["https://i.discogs.com/thumb.jpg", None],
        "relation_to_catalog_album_ids": ["master-1", None],
        "caveat_flags": [0, 1],
        "caveat_flag_names": list(CAVEAT_FLAG_NAMES),
    }


def _registry() -> dict[str, Any]:
    catalog = _catalog()
    fields = _base_fields()
    registry = {
        "schema_version": 2,
        "catalog_version": catalog["catalog_version"],
        "generated_at": "2026-08-07T00:00:00+00:00",
        "source": "Union of challenge/routes/pathfinding-graph release ids.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        **fields,
    }
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    return registry


def test_clean_registry_has_no_failures() -> None:
    assert evidence_release_registry_failures(_registry(), _catalog()) == []


def test_wrong_top_level_type_fails() -> None:
    assert evidence_release_registry_failures("not a dict", _catalog()) != []
    assert evidence_release_registry_failures(_registry(), "not a dict") != []


def test_mismatched_catalog_version_is_caught() -> None:
    registry = deepcopy(_registry())
    registry["catalog_version"] = "catalog-v1-wrong"
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("catalog_version" in f for f in failures)


def test_stale_version_is_caught() -> None:
    registry = deepcopy(_registry())
    registry["evidence_release_registry_version"] = (
        "evidence-release-registry-v1-20260601-" + "0" * 12
    )
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("evidence_release_registry_version" in f for f in failures)


def test_unsorted_release_ids_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["release_ids"] = [2, 1]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("sorted and deduplicated" in f for f in failures)


def test_mismatched_array_length_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["titles"] = ["Only One"]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("titles has length" in f for f in failures)


def test_implausible_year_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["years"] = [3000, None]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("plausible release-year range" in f for f in failures)


def test_non_https_source_url_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["source_urls"] = ["ftp://example.invalid", "https://data.discogs.com/?download=fake"]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("source_urls[0]" in f for f in failures)


def test_cover_art_not_hotlinking_approved_host_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["cover_uri150s"] = ["https://evil.example/rehosted.jpg", None]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("cover_uri150s[0]" in f for f in failures)


def test_relation_to_unknown_catalog_album_is_rejected() -> None:
    registry = deepcopy(_registry())
    registry["relation_to_catalog_album_ids"] = ["master-999", None]
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("relation_to_catalog_album_ids[0]" in f for f in failures)


def test_empty_registry_is_valid() -> None:
    catalog = _catalog()
    registry = {
        "schema_version": 2,
        "catalog_version": catalog["catalog_version"],
        "generated_at": "2026-08-07T00:00:00+00:00",
        "source": "Union of challenge/routes/pathfinding-graph release ids.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "release_ids": [],
        "titles": [],
        "years": [],
        "countries": [],
        "master_ids": [],
        "source_urls": [],
        "cover_uri150s": [],
        "relation_to_catalog_album_ids": [],
        "caveat_flags": [],
        "caveat_flag_names": list(CAVEAT_FLAG_NAMES),
    }
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    assert evidence_release_registry_failures(registry, catalog) == []


# --- v2 caveat flags (ADR 0059) -----------------------------------------


def test_v1_payloads_still_validate() -> None:
    """The schema bump must not orphan an already-published artifact: the
    Pi fleet and the web build both validate whatever is on disk, and a
    registry regenerates independently of the validator that ships."""
    registry = _registry()
    registry["schema_version"] = 1
    registry.pop("caveat_flags")
    registry.pop("caveat_flag_names")
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    assert evidence_release_registry_failures(registry, _catalog()) == []


def test_v2_requires_the_caveat_fields() -> None:
    registry = _registry()
    registry.pop("caveat_flags")
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("unexpected top-level keys" in f for f in failures)


def test_a_legend_that_disagrees_with_the_contract_is_a_failure() -> None:
    """The legend IS the bit order. A payload that reorders it is one whose
    integers mean something else -- silently relabelled caveats in the UI
    would be worse than a hard build failure."""
    registry = _registry()
    registry["caveat_flag_names"] = list(reversed(CAVEAT_FLAG_NAMES))
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("published bit order" in f for f in failures)


def test_flags_outside_the_published_legend_are_rejected() -> None:
    registry = _registry()
    registry["caveat_flags"] = [1 << len(CAVEAT_FLAG_NAMES)]
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    failures = evidence_release_registry_failures(registry, _catalog())
    assert any("outside the published legend" in f for f in failures)


def test_the_version_identity_pool_includes_caveat_flags() -> None:
    """Adding a field without folding it into the content hash would leave
    a version string describing content it never saw."""
    registry = _registry()
    before = evidence_release_registry_version(registry, _SNAPSHOT)
    registry["caveat_flags"] = [1]
    assert evidence_release_registry_version(registry, _SNAPSHOT) != before


@pytest.mark.parametrize(
    ("descriptors", "expected"),
    [
        (frozenset(), 0),
        (frozenset({"Album"}), 0),
        (frozenset({"Compilation"}), 1),
        (frozenset({"Reissue"}), 1 << 3),
        # Repress and Reissue share one bit: both mean "not the original
        # pressing", and a player does not need them told apart.
        (frozenset({"Repress"}), 1 << 3),
        (frozenset({"Unofficial Release"}), 1 << 5),
        (frozenset({"Compilation", "Unofficial Release"}), 1 | (1 << 5)),
    ],
)
def test_caveat_flags_for_descriptors(descriptors: frozenset[str], expected: int) -> None:
    assert caveat_flags_for_descriptors(descriptors) == expected


def test_no_descriptor_produces_a_positive_quality_claim() -> None:
    """The deliberate absence being pinned: there is no `studio_album` flag,
    because `docs/RELEASE_FORMAT_RESEARCH.md` measured 94.7% of a known
    false-positive population carrying only a bare `Album` descriptor. A
    future edit that adds one has to delete this test and say why."""
    assert "studio_album" not in CAVEAT_FLAG_NAMES
    assert caveat_flags_for_descriptors(frozenset({"Album", "LP", "Stereo"})) == 0
