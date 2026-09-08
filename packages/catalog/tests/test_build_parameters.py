"""Tests for build-parameter resolution (graph-expansion plan Y3 follow-up).

Pure functions, no DuckDB fixture -- which is the point of putting the
precedence rules in their own module rather than inline in a CLI handler.
"""

from __future__ import annotations

import pytest

from networked_players_catalog.build_parameters import (
    RECORD_ROUTES_DEFAULT_BUILD_PARAMETERS,
    BuildParametersError,
    Resolution,
    format_build_parameters_report,
    read_previous_build_parameters,
    resolve_build_parameters,
    summary,
    values,
)

_ROUTES_DEFAULTS = RECORD_ROUTES_DEFAULT_BUILD_PARAMETERS


def test_cli_value_wins_over_inherited_and_default() -> None:
    resolved = resolve_build_parameters(
        supplied={"two_hop_target": 250},
        previous={"two_hop_target": 200},
        defaults=_ROUTES_DEFAULTS,
    )
    assert resolved["two_hop_target"] == Resolution(250, "cli")


def test_inherited_wins_over_default_when_no_cli_value() -> None:
    """The real Round 1 regression, at the unit level: the published artifact
    held 200 two-hop rounds and the CLI default is 100."""
    resolved = resolve_build_parameters(
        supplied={"two_hop_target": None},
        previous={"one_hop_target": 150, "two_hop_target": 200},
        defaults=_ROUTES_DEFAULTS,
    )
    assert resolved["two_hop_target"] == Resolution(200, "inherited")
    assert resolved["one_hop_target"] == Resolution(150, "inherited")
    # Not in the previous block at all -> falls back, not inherited.
    assert resolved["max_bridge_share"] == Resolution(0.2, "default")


def test_default_applies_when_nothing_is_supplied_or_recorded() -> None:
    resolved = resolve_build_parameters(supplied={}, previous=None, defaults=_ROUTES_DEFAULTS)
    assert {name: r.source for name, r in resolved.items()} == {
        name: "default" for name in _ROUTES_DEFAULTS
    }
    assert values(resolved) == _ROUTES_DEFAULTS


def test_inherited_null_max_frontier_expansion_is_not_treated_as_absent() -> None:
    """The falsy landmine. The runbook passes `--max-frontier-expansion 0`,
    the handler converts it to `None`, and the artifact stamps `null` --
    which the contract explicitly permits. Resolving by truthiness would
    silently re-enable a frontier bound the operator deliberately disabled."""
    resolved = resolve_build_parameters(
        supplied={"max_frontier_expansion": None},
        previous={"max_frontier_expansion": None},
        defaults={"max_frontier_expansion": 300},
    )
    assert resolved["max_frontier_expansion"] == Resolution(None, "inherited")


def test_inherited_zero_expansion_round_is_not_treated_as_absent() -> None:
    """Same landmine, integer flavour: `0` is the real, documented value for
    the original backbone."""
    resolved = resolve_build_parameters(
        supplied={"expansion_round": None},
        previous={"expansion_round": 0},
        defaults={"expansion_round": 7},
    )
    assert resolved["expansion_round"] == Resolution(0, "inherited")


def test_inherited_zero_target_is_not_treated_as_absent() -> None:
    resolved = resolve_build_parameters(
        supplied={"two_hop_target": None},
        previous={"two_hop_target": 0},
        defaults=_ROUTES_DEFAULTS,
    )
    assert resolved["two_hop_target"] == Resolution(0, "inherited")


# --- reading the block off a previous artifact ------------------------------


def test_missing_block_reports_nothing_inherited() -> None:
    """Every committed artifact looked like this before PR #248 landed."""
    assert read_previous_build_parameters({"provenance": {}}, flag="--x", at="provenance") is None
    assert read_previous_build_parameters({"albums": []}, flag="--x") is None


def test_block_is_read_from_provenance_or_top_level_as_directed() -> None:
    block = {"two_hop_target": 200}
    assert (
        read_previous_build_parameters(
            {"provenance": {"build_parameters": block}}, flag="--x", at="provenance"
        )
        == block
    )
    assert read_previous_build_parameters({"build_parameters": block}, flag="--x") == block


def test_a_block_in_provenance_is_not_found_at_top_level() -> None:
    """Guards against pointing a builder at the wrong location and silently
    getting `None` -- which would look exactly like 'nothing recorded'."""
    payload = {"provenance": {"build_parameters": {"two_hop_target": 200}}}
    assert read_previous_build_parameters(payload, flag="--x", at="top_level") is None


def test_malformed_block_raises_naming_the_flag() -> None:
    with pytest.raises(BuildParametersError, match="--previous-routes-universe"):
        read_previous_build_parameters(
            {"provenance": {"build_parameters": [1, 2, 3]}},
            flag="--previous-routes-universe",
            at="provenance",
        )


def test_malformed_provenance_raises_rather_than_reporting_absent() -> None:
    with pytest.raises(BuildParametersError, match="provenance is not an object"):
        read_previous_build_parameters(
            {"provenance": "nope"}, flag="--carry-forward-challenge", at="provenance"
        )


def test_non_object_artifact_raises() -> None:
    with pytest.raises(BuildParametersError, match="does not contain a JSON object"):
        read_previous_build_parameters([1, 2], flag="--already-published-catalog")


# --- reporting --------------------------------------------------------------


def test_report_names_every_parameter_and_its_source() -> None:
    resolved = resolve_build_parameters(
        supplied={"two_hop_target": 250},
        previous={"one_hop_target": 150},
        defaults=_ROUTES_DEFAULTS,
    )
    report = format_build_parameters_report(
        resolved, command="build-record-routes", previous_label="routes/universe.v1.json"
    )
    assert "routes/universe.v1.json" in report
    for name in _ROUTES_DEFAULTS:
        assert name in report
    assert "250 (cli)" in report
    assert "150 (inherited)" in report
    assert "0.2 (default)" in report


def test_report_is_loudest_when_no_previous_artifact_was_given() -> None:
    """Piggybacking inheritance onto an optional flag means forgetting the
    flag returns you to the original failure. That case must be stated, not
    silently skipped."""
    resolved = resolve_build_parameters(supplied={}, previous=None, defaults=_ROUTES_DEFAULTS)
    report = format_build_parameters_report(
        resolved, command="build-record-routes", previous_label=None
    )
    assert "no previous artifact given" in report
    assert "nothing inherited" in report


def test_summary_is_json_shaped_for_the_stdout_payload() -> None:
    resolved = resolve_build_parameters(
        supplied={"two_hop_target": 250}, previous=None, defaults={"two_hop_target": 100}
    )
    assert summary(resolved) == {"two_hop_target": {"value": 250, "source": "cli"}}
