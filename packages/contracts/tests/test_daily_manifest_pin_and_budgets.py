"""Atlas F4a/F4b: the played-dates pin and the payload budgets."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from networked_players_contracts import (
    advance_pin,
    build_pin,
    daily_manifest_pin_failures,
    payload_budget_report,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _manifest(days: int = 20, start: date = date(2026, 11, 1)) -> dict[str, Any]:
    return {
        "schedule": [
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "generation": "gen-1" if i < 10 else "gen-2",
                "round_id": f"conn-{i:010x}",
                "round_fingerprint": f"rfp-{i:016x}",
            }
            for i in range(days)
        ]
    }


def test_unchanged_manifest_matches_pin() -> None:
    manifest = _manifest()
    assert daily_manifest_pin_failures(manifest, build_pin(manifest, "2026-11-10")) == []


def test_changed_past_date_fails_and_names_the_first_differing_date() -> None:
    manifest = _manifest()
    pin = build_pin(manifest, "2026-11-10")
    mutated = deepcopy(manifest)
    # Another valid-looking round for an already-played date (and a later one).
    mutated["schedule"][6]["round_id"] = "conn-aaaaaaaaaa"
    mutated["schedule"][8]["round_fingerprint"] = "rfp-bbbbbbbbbbbbbbbb"
    failures = daily_manifest_pin_failures(mutated, pin)
    assert len(failures) == 1
    assert "first difference: pinned date 2026-11-07 was changed" in failures[0]
    assert "2 difference(s)" in failures[0]


def test_changed_generation_of_a_played_date_fails() -> None:
    manifest = _manifest()
    pin = build_pin(manifest, "2026-11-10")
    mutated = deepcopy(manifest)
    mutated["schedule"][3]["generation"] = "gen-2"
    assert "2026-11-04" in daily_manifest_pin_failures(mutated, pin)[0]


def test_removed_played_date_fails() -> None:
    manifest = _manifest()
    pin = build_pin(manifest, "2026-11-10")
    mutated = deepcopy(manifest)
    del mutated["schedule"][0]
    assert "2026-11-01 is missing" in daily_manifest_pin_failures(mutated, pin)[0]


def test_future_dates_may_be_rewritten_and_appended_without_failing() -> None:
    manifest = _manifest()
    pin = build_pin(manifest, "2026-11-10")
    rewritten = deepcopy(manifest)
    rewritten["schedule"][15]["round_id"] = "conn-cccccccccc"  # after the pin: a cutover rewrite
    rewritten["schedule"].extend(_manifest(30)["schedule"][20:])  # appended dates
    assert daily_manifest_pin_failures(rewritten, pin) == []


def test_malformed_pin_is_reported() -> None:
    manifest = _manifest()
    assert daily_manifest_pin_failures(manifest, "nope")
    pin = build_pin(manifest, "2026-11-10")
    assert daily_manifest_pin_failures(manifest, {**pin, "extra": 1})
    assert daily_manifest_pin_failures(manifest, {**pin, "pinned_through": "soon"})


def test_advance_pin_moves_forward_and_is_idempotent() -> None:
    manifest = _manifest()
    first = advance_pin(manifest, None, "2026-11-05", as_of="2026-11-16")
    second = advance_pin(manifest, first, "2026-11-10", as_of="2026-11-16")
    assert second["entry_count"] == 10
    assert advance_pin(manifest, second, "2026-11-10", as_of="2026-11-16") == second


@pytest.mark.parametrize(
    ("through", "as_of", "fragment"),
    [
        ("2026-11-08", "2026-11-16", "backwards"),
        ("2026-11-16", "2026-11-16", "strictly before"),
        ("2026-11-30", "2026-12-31", "beyond the manifest's last date"),
        ("2026-10-01", "2026-11-16", "before the manifest's first date"),
        ("not-a-date", "2026-11-16", "not a valid ISO date"),
    ],
)
def test_advance_pin_refusals(through: str, as_of: str, fragment: str) -> None:
    manifest = _manifest()
    existing = build_pin(manifest, "2026-11-10")
    with pytest.raises(ValueError, match=fragment):
        advance_pin(manifest, existing, through, as_of=as_of)


def test_advance_pin_refuses_when_the_pinned_prefix_changed() -> None:
    manifest = _manifest()
    existing = build_pin(manifest, "2026-11-05")
    mutated = deepcopy(manifest)
    mutated["schedule"][1]["round_id"] = "conn-dddddddddd"
    with pytest.raises(ValueError, match="no longer matches"):
        advance_pin(mutated, existing, "2026-11-12", as_of="2026-11-16")


def test_committed_pin_matches_committed_manifest_and_is_in_the_past() -> None:
    manifest = json.loads(
        (_REPO_ROOT / "apps/web/public/data/game/daily-manifest.v1.json").read_text()
    )
    pin = json.loads((_REPO_ROOT / "data/integrity/daily-manifest-pin-v1.json").read_text())
    assert daily_manifest_pin_failures(manifest, pin) == []
    assert pin["entry_count"] > 0


# --- payload budgets -------------------------------------------------------


def _budgets(**overrides: int) -> dict[str, int]:
    return {
        "schema_version": 1,
        "graph_gzip_hard_bytes": 2_500_000,
        "graph_gzip_warn_bytes": 2_000_000,
        "data_total_raw_hard_bytes": 60_000_000,
        **overrides,
    }


def _data_root(tmp_path: Path, graph_bytes: bytes) -> Path:
    (tmp_path / "pathfinding").mkdir()
    (tmp_path / "pathfinding" / "graph.v4.json").write_bytes(graph_bytes)
    return tmp_path


def test_small_graph_is_within_budget(tmp_path: Path) -> None:
    root = _data_root(tmp_path, b'{"nodes": []}')
    report = payload_budget_report(root, _budgets())
    assert report["failures"] == [] and report["warnings"] == []
    assert report["measured"]["graph_gzip_bytes"] > 0


def test_oversized_incompressible_graph_fails_the_hard_budget(tmp_path: Path) -> None:
    # Pseudo-random bytes do not compress, so the gzip size tracks the raw size.
    import random

    blob = random.Random(0).randbytes(3_000)
    root = _data_root(tmp_path, blob)
    report = payload_budget_report(
        root, _budgets(graph_gzip_hard_bytes=2_000, graph_gzip_warn_bytes=1_000)
    )
    assert any("hard budget" in f for f in report["failures"])


def test_graph_between_warn_and_hard_is_data_not_failure(tmp_path: Path) -> None:
    import random

    root = _data_root(tmp_path, random.Random(1).randbytes(3_000))
    report = payload_budget_report(
        root, _budgets(graph_gzip_hard_bytes=100_000, graph_gzip_warn_bytes=1_000)
    )
    assert report["failures"] == []
    assert len(report["warnings"]) == 1


def test_total_raw_ceiling_fails(tmp_path: Path) -> None:
    root = _data_root(tmp_path, b"{}")
    (root / "big.bin").write_bytes(b"x" * 5_000)
    report = payload_budget_report(root, _budgets(data_total_raw_hard_bytes=1_000))
    assert any("hard ceiling" in f for f in report["failures"])


def test_bad_budget_files_are_reported(tmp_path: Path) -> None:
    root = _data_root(tmp_path, b"{}")
    assert payload_budget_report(root, {"schema_version": 1})["failures"]
    assert payload_budget_report(root, _budgets(graph_gzip_warn_bytes=3_000_000))["failures"]
    assert payload_budget_report(root, _budgets(graph_gzip_hard_bytes=0))["failures"]


def test_committed_budgets_hold_for_committed_artifacts() -> None:
    budgets = json.loads((_REPO_ROOT / "data/integrity/payload-budgets-v1.json").read_text())
    report = payload_budget_report(_REPO_ROOT / "apps/web/public/data", budgets)
    assert report["failures"] == []
    # Headroom guard: the raw ceiling is meant to be generous, not tight.
    assert report["measured"]["data_total_raw_bytes"] * 1.5 < budgets["data_total_raw_hard_bytes"]
