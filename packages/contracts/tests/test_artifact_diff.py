from __future__ import annotations

from networked_players_contracts.artifact_diff import artifact_diff
from networked_players_contracts.canonical import content_hash


def test_identical_payloads_short_circuit_even_with_different_key_order() -> None:
    old = {"a": 1, "b": 2}
    new = {"b": 2, "a": 1}
    report = artifact_diff(old, new)
    assert report == {
        "identical": True,
        "content_hash": content_hash(old),
        "version_field_changes": {},
        "structural_diff": [],
    }


def test_a_version_field_change_is_called_out_specifically() -> None:
    old = {"catalog_version": "catalog-v1-old", "albums": []}
    new = {"catalog_version": "catalog-v1-new", "albums": []}
    report = artifact_diff(old, new)
    assert report["identical"] is False
    assert report["version_field_changes"] == {
        "catalog_version": {"old": "catalog-v1-old", "new": "catalog-v1-new"}
    }


def test_an_added_and_removed_key_are_both_reported() -> None:
    old = {"kept": 1, "removed": "gone"}
    new = {"kept": 1, "added": "new"}
    report = artifact_diff(old, new)
    diffs = {(d["path"], d["change"]) for d in report["structural_diff"]}
    assert ("$.removed", "removed") in diffs
    assert ("$.added", "added") in diffs


def test_a_changed_nested_value_is_reported_with_its_full_path() -> None:
    old = {"contributors": [{"artist_id": 1, "name": "Alice"}]}
    new = {"contributors": [{"artist_id": 1, "name": "Alicia"}]}
    report = artifact_diff(old, new)
    assert report["structural_diff"] == [
        {
            "path": "$.contributors[0].name",
            "change": "changed",
            "old": "Alice",
            "new": "Alicia",
        }
    ]


def test_a_list_length_change_is_reported_directly_not_element_by_element() -> None:
    old = {"albums": ["a", "b"]}
    new = {"albums": ["a", "b", "c"]}
    report = artifact_diff(old, new)
    assert report["structural_diff"] == [
        {
            "path": "$.albums",
            "change": "list-length-changed",
            "old_length": 2,
            "new_length": 3,
        }
    ]


def test_a_version_field_nested_under_provenance_is_reported_with_its_path() -> None:
    """`challenge.v2.json` and `game/rounds.v1.json` store every version field
    under a `provenance` object rather than at the top level. A top-level-only
    lookup silently reported `{}` here even though the fields genuinely
    changed -- still visible in `structural_diff`, just missing from the one
    summary this function exists to provide."""
    old = {"provenance": {"catalog_version": "catalog-v1-old", "note": "x"}}
    new = {"provenance": {"catalog_version": "catalog-v1-new", "note": "x"}}
    report = artifact_diff(old, new)
    assert report["version_field_changes"] == {
        "provenance.catalog_version": {"old": "catalog-v1-old", "new": "catalog-v1-new"}
    }


def test_top_level_and_nested_version_fields_are_both_reported_independently() -> None:
    old = {
        "catalog_version": "catalog-v1-old",
        "provenance": {"pool_version": "pool-v1-old"},
    }
    new = {
        "catalog_version": "catalog-v1-new",
        "provenance": {"pool_version": "pool-v1-new"},
    }
    report = artifact_diff(old, new)
    assert report["version_field_changes"] == {
        "catalog_version": {"old": "catalog-v1-old", "new": "catalog-v1-new"},
        "provenance.pool_version": {"old": "pool-v1-old", "new": "pool-v1-new"},
    }


def test_a_version_field_absent_from_both_sides_is_not_reported() -> None:
    old = {"provenance": {"note": "x"}}
    new = {"provenance": {"note": "y"}}
    report = artifact_diff(old, new)
    assert report["version_field_changes"] == {}


def test_registry_and_membership_version_fields_are_reported() -> None:
    """Both shipped after `_VERSION_FIELD_NAMES` was written and were
    missing from it, so a regenerated evidence registry diffed without the
    one line a publisher most needs. Regression-pinned per field rather
    than asserting the set's contents, so the test states the behaviour
    rather than restating the constant."""
    for field in ("evidence_release_registry_version", "album_credit_membership_version"):
        report = artifact_diff({field: "a"}, {field: "b"})
        assert field in report["version_field_changes"], field
        assert report["version_field_changes"][field]["old"] == "a"
        assert report["version_field_changes"][field]["new"] == "b"


def test_contributor_index_companion_version_fields_are_reported() -> None:
    """`album_hop_distances_version` and `background_only_profiles_version`
    (ADR 0048/0060 addenda) are the same recurring gap this file's own
    comment already documents once: a new artifact's version field shipped
    without a matching addition to `_VERSION_FIELD_NAMES`, real Codex
    review findings for both (round 7 caught `background_only_profiles_
    version` missing; `album_hop_distances_version` was found missing by
    inspection while fixing that finding)."""
    for field in ("album_hop_distances_version", "background_only_profiles_version"):
        report = artifact_diff({field: "a"}, {field: "b"})
        assert field in report["version_field_changes"], field
        assert report["version_field_changes"][field]["old"] == "a"
        assert report["version_field_changes"][field]["new"] == "b"
