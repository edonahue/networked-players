"""Approved-pool validator (ADR 0072 section 2): shape and the two-way check."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from networked_players_contracts.approved_pool import (
    approved_pool_catalog_failures,
    approved_pool_failures,
    seed_approved_pool_from_catalog,
)
from networked_players_contracts.public_artifacts import PUBLIC_ARTIFACT_GROUPS

REPO_ROOT = Path(__file__).resolve().parents[3]


def _catalog() -> dict[str, Any]:
    return {
        "albums": [
            {"master_id": 1, "expansion_round": 0, "selection_source": "editorial"},
            {"master_id": 2, "expansion_round": 1, "selection_source": "graph_rich"},
        ]
    }


def _pool() -> dict[str, Any]:
    return seed_approved_pool_from_catalog(_catalog(), note="synthetic")


def test_a_consistent_pair_passes() -> None:
    assert approved_pool_failures(_pool()) == []
    assert approved_pool_catalog_failures(_pool(), _catalog()) == []


def test_catalog_album_missing_from_pool_fails() -> None:
    pool = _pool()
    pool["albums"] = pool["albums"][:1]
    failures = approved_pool_catalog_failures(pool, _catalog())
    assert any("not in the approved pool" in f and "2" in f for f in failures)


def test_pool_album_missing_from_catalog_fails() -> None:
    catalog = _catalog()
    catalog["albums"] = catalog["albums"][:1]
    failures = approved_pool_catalog_failures(_pool(), catalog)
    assert any("absent from the catalog" in f and "2" in f for f in failures)


def test_round_and_label_disagreement_fail() -> None:
    pool = _pool()
    pool["albums"][0]["round"] = 3
    pool["albums"][1]["selection_source"] = "editorial"
    failures = approved_pool_catalog_failures(pool, _catalog())
    assert any("expansion_round" in f for f in failures)
    assert any("selection_source" in f for f in failures)


def test_v1_catalog_without_label_fields_only_checks_the_master_set() -> None:
    catalog = {"albums": [{"master_id": 1}, {"master_id": 2}]}
    assert approved_pool_catalog_failures(_pool(), catalog) == []


def test_extra_private_looking_keys_are_rejected() -> None:
    pool = _pool()
    pool["albums"][0]["score"] = 0.9
    pool["reviewer"] = "someone"
    failures = approved_pool_failures(pool)
    assert any("exactly" in f for f in failures)
    assert any("top-level" in f for f in failures)


def test_personal_editorial_bad_order_and_duplicates_are_rejected() -> None:
    pool = _pool()
    pool["albums"][0]["selection_source"] = "personal_editorial"
    assert any("selection_source" in f for f in approved_pool_failures(pool))
    pool = _pool()
    pool["albums"].reverse()
    assert any("sorted" in f for f in approved_pool_failures(pool))
    pool = _pool()
    pool["albums"].append(copy.deepcopy(pool["albums"][0]))
    assert any("more than once" in f for f in approved_pool_failures(pool))


def test_group_is_registered() -> None:
    assert "approved_pool" in PUBLIC_ARTIFACT_GROUPS


def test_the_real_committed_pool_matches_the_real_committed_catalog() -> None:
    pool = json.loads((REPO_ROOT / "data/albums/approved-pool-v1.json").read_text())
    catalog = json.loads((REPO_ROOT / "apps/web/public/data/catalog/albums.v1.json").read_text())
    assert approved_pool_failures(pool) == []
    assert approved_pool_catalog_failures(pool, catalog) == []
    assert len(pool["albums"]) == len(catalog["albums"])
    assert seed_approved_pool_from_catalog(catalog, note=pool["note"]) == pool


def test_a_malformed_catalog_is_a_failure_not_a_pass() -> None:
    pool = {
        "schema_version": 1,
        "note": "synthetic",
        "albums": [{"master_id": 7, "round": 0, "selection_source": "editorial"}],
    }
    assert approved_pool_failures(pool) == []
    for broken in (None, [], {"albums": "nope"}):
        assert approved_pool_catalog_failures(pool, broken) != []


def test_a_master_listed_twice_in_the_catalog_fails() -> None:
    pool = {
        "schema_version": 1,
        "note": "synthetic",
        "albums": [{"master_id": 7, "round": 0, "selection_source": "editorial"}],
    }
    catalog = {"albums": [{"master_id": 7}, {"master_id": 7}]}
    failures = approved_pool_catalog_failures(pool, catalog)
    assert any("more than once" in f for f in failures)
