"""Round seed spec contract (Campaign Atlas SS): shape, lane quotas, committed fixture."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from networked_players_contracts.round_seed_spec import lane_quotas, round_seed_spec_failures

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "data/fixtures/round-seed-spec/synthetic-round-seed-spec-v1.json"
)


def _spec() -> dict:
    return json.loads(FIXTURE.read_text())


def test_committed_synthetic_fixture_is_valid() -> None:
    assert round_seed_spec_failures(_spec()) == []


def test_non_object_is_rejected() -> None:
    assert round_seed_spec_failures([]) == ["round seed spec must be a JSON object"]


def test_unknown_keys_are_rejected_at_both_levels() -> None:
    spec = _spec()
    spec["owner_email"] = "x"
    spec["themes"][0]["notes_from_collection"] = "x"
    text = " ".join(round_seed_spec_failures(spec))
    assert "owner_email" in text and "notes_from_collection" in text


def test_lane_shares_must_sum_to_100_with_exact_keys() -> None:
    spec = _spec()
    spec["lane_shares_percent"]["theme"] = 50
    assert any("sum to 100" in f for f in round_seed_spec_failures(spec))
    spec["lane_shares_percent"] = {"theme": 100}
    assert any("exactly the keys" in f for f in round_seed_spec_failures(spec))


def test_theme_needs_a_seed_and_valid_ids() -> None:
    spec = _spec()
    spec["themes"][0]["seed_artist_ids"] = []
    assert any("at least one seed" in f for f in round_seed_spec_failures(spec))
    spec = _spec()
    spec["themes"][0]["seed_artist_ids"] = [0, True, 5, 5]
    assert any("positive integers" in f for f in round_seed_spec_failures(spec))


def test_bounds_and_caps_must_be_stated_and_sane() -> None:
    spec = _spec()
    theme = spec["themes"][0]
    theme["year_min"], theme["year_max"] = 2010, 1990
    del theme["candidate_cap"]
    theme["min_shared_performers"] = 0
    failures = " ".join(round_seed_spec_failures(spec))
    assert "must not exceed" in failures
    assert "candidate_cap" in failures
    assert "min_shared_performers" in failures


def test_duplicate_theme_names_rejected() -> None:
    spec = _spec()
    spec["themes"][1] = copy.deepcopy(spec["themes"][0])
    assert any("unique" in f for f in round_seed_spec_failures(spec))


def test_lane_quotas_sum_to_target_by_largest_remainder() -> None:
    assert lane_quotas(_spec()) == {"theme": 12, "graph_value": 5, "coverage_repair": 3}
    spec = _spec()
    spec["target_count"] = 60
    assert lane_quotas(spec) == {"theme": 36, "graph_value": 15, "coverage_repair": 9}
    spec["target_count"] = 7
    quotas = lane_quotas(spec)
    assert sum(quotas.values()) == 7 and quotas["theme"] == 4


def test_non_string_and_whitespace_variant_names_return_failures_not_exceptions() -> None:
    spec = _spec()
    spec["themes"][0]["name"] = ["unhashable"]
    spec["themes"][1]["name"] = 7
    failures = round_seed_spec_failures(spec)
    assert sum("name must be a non-empty string" in f for f in failures) == 2
    spec = _spec()
    spec["themes"][1]["name"] = spec["themes"][0]["name"] + " "
    failures = round_seed_spec_failures(spec)
    assert any("leading or trailing whitespace" in f for f in failures)
    spec["themes"][1]["name"] = spec["themes"][0]["name"].upper()
    assert any("unique" in f for f in round_seed_spec_failures(spec))
