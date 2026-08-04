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
