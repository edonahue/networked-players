"""Tests for the schema-v2 multi-generation Connection Guesser daily
manifest (Phase 7 catalog-expansion migration). Reuses the v1 test file's
fixture builders (`_one_hop_round`, `_rounds_artifact`, `_round_id`,
`_real_pool`, `PROVENANCE`, `GENERATED_AT`) so v1 and v2 tests exercise
provably identical round/provenance shapes."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from networked_players_graph_core.connection_daily_manifest import (
    CONNECTION_DAILY_MANIFEST_MODE,
    CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2,
    ConnectionDailyManifestError,
    build_connection_daily_manifest,
    migrate_connection_daily_manifest_generation,
    upgrade_connection_daily_manifest_to_v2,
    validate_connection_daily_manifest_v2,
)
from test_connection_daily_manifest import (
    GENERATED_AT,
    PROVENANCE,
    _one_hop_round,
    _real_pool,
    _round_id,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DAILY_MANIFEST = REPO_ROOT / "apps/web/public/data/game/daily-manifest.v1.json"
# Connection of the Day's real, already-published launch date. Immutable by
# definition -- if this ever changes, real shared links stopped resolving.
REAL_LAUNCH_DATE = "2026-07-22"

GEN2_PROVENANCE = {
    **PROVENANCE,
    "catalog_version": "catalog-v1-20260601-newcat",
    "pool_version": "connection-v1-20260601-newpool",
    "artifact_version": "connection-artifact-v1-20260601-newart",
}


def _real_pool_gen2(n: int = 6) -> dict[str, Any]:
    rounds = [
        _one_hop_round(_round_id(100 + i), f"gen2-a{i}", f"gen2-c{i}", 2000 + i) for i in range(n)
    ]
    return {"schema_version": 1, "provenance": GEN2_PROVENANCE, "rounds": rounds}


def _v1_manifest(days: int = 5) -> dict[str, Any]:
    return build_connection_daily_manifest(
        _real_pool(), start_date="2026-07-22", days=days, generated_at=GENERATED_AT
    )


# --- upgrade_connection_daily_manifest_to_v2 --------------------------------


def test_upgrade_to_v2_is_lossless_for_every_existing_entry() -> None:
    v1 = _v1_manifest(days=5)
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    assert v2["schema_version"] == 2
    assert v2["mode"] == CONNECTION_DAILY_MANIFEST_MODE
    assert v2["generated_at"] == v1["generated_at"]
    assert v2["start_date"] == v1["start_date"]
    assert len(v2["schedule"]) == len(v1["schedule"])
    for old_entry, new_entry in zip(v1["schedule"], v2["schedule"], strict=True):
        assert new_entry["date"] == old_entry["date"]
        assert new_entry["round_id"] == old_entry["round_id"]
        assert new_entry["round_fingerprint"] == old_entry["round_fingerprint"]
        assert new_entry["generation"] == "gen-1"


def test_upgrade_to_v2_records_the_v1_provenance_as_generation_one() -> None:
    v1 = _v1_manifest()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    assert v2["generations"] == [
        {
            "generation_id": "gen-1",
            "catalog_version": v1["catalog_version"],
            "pool_version": v1["pool_version"],
            "artifact_version": v1["artifact_version"],
            "rounds_url": "/data/game/generations/gen-1/rounds.json",
        }
    ]


@pytest.mark.skipif(
    not REAL_DAILY_MANIFEST.is_file(), reason="real committed daily manifest not present"
)
def test_upgrade_preserves_every_one_of_the_real_committed_manifest_entries() -> None:
    """The historical-immutability proof this whole design exists for, run
    against the REAL production artifact, not a fixture.

    Deliberately schema-AWARE rather than pinned to v1: the real file was
    v1 until the Phase 7 gen-1 -> gen-2 cutover and is v2 after it, and this
    check must keep protecting real published history in BOTH worlds rather
    than start failing the moment the migration it was written to justify
    actually happened.

    - While the real file is v1: every currently-published date survives the
      v1 -> v2 structural upgrade byte-identical (date/round_id/
      round_fingerprint), in order, gaining only a `generation` tag.
      `upgrade_connection_daily_manifest_to_v2` is pure structure -- it never
      reads round content or recomputes a fingerprint -- so this needs no
      rounds artifact to prove it.
    - Once the real file is v2: the launch date is still the real launch
      date, the schedule is still gap-free and duplicate-free, every entry
      names a generation the manifest actually declares, and generations
      appear in contiguous blocks (a retired generation's dates are never
      interleaved with a later one's). Those are the properties an
      already-played, already-shared date depends on.
    """
    real = json.loads(REAL_DAILY_MANIFEST.read_text())

    if real["schema_version"] == 1:
        real_schedule_before = deepcopy(real["schedule"])
        assert real_schedule_before, "the real manifest must never be empty"

        v2 = upgrade_connection_daily_manifest_to_v2(
            real, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
        )

        assert len(v2["schedule"]) == len(real_schedule_before)
        for original, upgraded in zip(real_schedule_before, v2["schedule"], strict=True):
            assert upgraded["date"] == original["date"]
            assert upgraded["round_id"] == original["round_id"]
            assert upgraded["round_fingerprint"] == original["round_fingerprint"]
            assert upgraded["generation"] == "gen-1"
        assert v2["schedule"][0]["date"] == REAL_LAUNCH_DATE
        return

    assert real["schema_version"] == CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2
    schedule = real["schedule"]
    assert schedule, "the real manifest must never be empty"
    # The real launch date is immutable -- losing it would mean a visitor's
    # earliest shared date stopped resolving.
    assert schedule[0]["date"] == REAL_LAUNCH_DATE
    assert real["start_date"] == REAL_LAUNCH_DATE

    declared = [g["generation_id"] for g in real["generations"]]
    assert declared, "a v2 manifest must declare at least one generation"
    assert len(declared) == len(set(declared)), "duplicate generation_id"

    seen_dates: set[str] = set()
    seen_round_ids: set[str] = set()
    previous: date | None = None
    blocks: list[str] = []
    for entry in schedule:
        assert entry["generation"] in declared, entry
        assert entry["date"] not in seen_dates, f"duplicate date {entry['date']}"
        seen_dates.add(entry["date"])
        assert entry["round_id"] not in seen_round_ids, (
            f"round {entry['round_id']} scheduled more than once across generations"
        )
        seen_round_ids.add(entry["round_id"])
        current = date.fromisoformat(entry["date"])
        if previous is not None:
            assert (current - previous).days == 1, f"gap or disorder before {entry['date']}"
        previous = current
        if not blocks or blocks[-1] != entry["generation"]:
            blocks.append(entry["generation"])
    # Each generation occupies ONE contiguous block: an older generation's
    # dates are never interleaved with a newer one's.
    assert len(blocks) == len(set(blocks)), f"generations are interleaved: {blocks}"


def test_upgrade_to_v2_rejects_a_non_v1_input() -> None:
    v1 = _v1_manifest()
    already_v2 = upgrade_connection_daily_manifest_to_v2(v1, generation_id="gen-1", rounds_url="x")
    with pytest.raises(ConnectionDailyManifestError, match="schema_version=1"):
        upgrade_connection_daily_manifest_to_v2(already_v2, generation_id="gen-2", rounds_url="y")


# --- migrate_connection_daily_manifest_generation ---------------------------


def _v2_manifest(days: int = 5) -> tuple[dict[str, Any], dict[str, Any]]:
    v1 = _v1_manifest(days=days)
    pool = _real_pool()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    return v2, pool


def test_migration_preserves_every_entry_before_the_cutover_date_exactly() -> None:
    """The one property the whole design exists to guarantee: every entry
    scheduled before the cutover date survives byte-identical -- same date,
    round_id, round_fingerprint, and generation -- through the migration."""
    v2, gen1_pool = _v2_manifest(days=10)
    original_schedule = deepcopy(v2["schedule"])
    cutover = v2["schedule"][5]["date"]  # keep the first 5, replace from index 5 onward

    migrated = migrate_connection_daily_manifest_generation(
        v2,
        _real_pool_gen2(),
        cutover_date=cutover,
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=10,
        generated_at="2026-07-23T00:00:00+00:00",
        existing_generation_rounds={"gen-1": gen1_pool},
    )

    kept = [e for e in migrated["schedule"] if e["date"] < cutover]
    assert kept == original_schedule[:5]


def test_migration_replaces_only_entries_on_or_after_cutover() -> None:
    v2, gen1_pool = _v2_manifest(days=10)
    cutover = v2["schedule"][5]["date"]
    old_removed_round_ids = {e["round_id"] for e in v2["schedule"][5:]}

    migrated = migrate_connection_daily_manifest_generation(
        v2,
        _real_pool_gen2(),
        cutover_date=cutover,
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=10,
        generated_at="2026-07-23T00:00:00+00:00",
        existing_generation_rounds={"gen-1": gen1_pool},
    )

    new_entries = [e for e in migrated["schedule"] if e["date"] >= cutover]
    assert all(e["generation"] == "gen-2" for e in new_entries)
    assert all(e["round_id"] not in old_removed_round_ids for e in new_entries)
    assert new_entries[0]["date"] == cutover


def test_migration_appends_exactly_one_new_generation() -> None:
    v2, gen1_pool = _v2_manifest(days=5)
    migrated = migrate_connection_daily_manifest_generation(
        v2,
        _real_pool_gen2(),
        cutover_date="2026-07-27",
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=5,
        generated_at="2026-07-23T00:00:00+00:00",
        existing_generation_rounds={"gen-1": gen1_pool},
    )
    assert [g["generation_id"] for g in migrated["generations"]] == ["gen-1", "gen-2"]
    assert migrated["generations"][0] == v2["generations"][0]  # gen-1 entry untouched


def test_migration_rejects_a_cutover_date_not_strictly_after_generated_at() -> None:
    v2, gen1_pool = _v2_manifest(days=5)
    with pytest.raises(ConnectionDailyManifestError, match="too soon after"):
        migrate_connection_daily_manifest_generation(
            v2,
            _real_pool_gen2(),
            cutover_date="2026-07-23",  # same day as generated_at below
            new_generation_id="gen-2",
            new_rounds_url="/data/game/rounds.v1.json",
            days=5,
            generated_at="2026-07-23T00:00:00+00:00",
            existing_generation_rounds={"gen-1": gen1_pool},
        )


def test_migration_rejects_a_cutover_date_one_day_after_generated_at() -> None:
    """The exact scenario a Codex review found: `apps/web/src/game/localDate.ts`
    rolls a date over at each PLAYER'S OWN local midnight, not UTC midnight, so
    a cutover only one day after `generated_at`'s own UTC date could already
    have been reached by a player in a timezone far ahead of UTC. A one-day
    margin (the original, too-weak check) must now be rejected; only a margin
    of `_MIN_CUTOVER_LEAD_DAYS` (2) full days or more is accepted."""
    v2, gen1_pool = _v2_manifest(days=5)
    with pytest.raises(ConnectionDailyManifestError, match="too soon after"):
        migrate_connection_daily_manifest_generation(
            v2,
            _real_pool_gen2(),
            cutover_date="2026-07-24",  # exactly one day after generated_at
            new_generation_id="gen-2",
            new_rounds_url="/data/game/rounds.v1.json",
            days=5,
            generated_at="2026-07-23T00:00:00+00:00",
            existing_generation_rounds={"gen-1": gen1_pool},
        )


def test_migration_rejects_a_cutover_date_in_the_past() -> None:
    v2, gen1_pool = _v2_manifest(days=5)
    with pytest.raises(ConnectionDailyManifestError, match="too soon after"):
        migrate_connection_daily_manifest_generation(
            v2,
            _real_pool_gen2(),
            cutover_date="2026-07-01",
            new_generation_id="gen-2",
            new_rounds_url="/data/game/rounds.v1.json",
            days=5,
            generated_at="2026-07-23T00:00:00+00:00",
            existing_generation_rounds={"gen-1": gen1_pool},
        )


def test_migration_rejects_a_cutover_that_would_leave_a_gap() -> None:
    """Real bug found while writing these tests: an operator-chosen cutover
    date further out than the day right after the last kept date would
    silently leave the published schedule with an unscheduled gap in the
    middle -- caught only much later by validate_connection_daily_manifest_v2,
    if at all. The migration itself must refuse this outright."""
    v2, gen1_pool = _v2_manifest(days=5)  # schedules 2026-07-22 .. 2026-07-26
    with pytest.raises(ConnectionDailyManifestError, match="gap or overlap"):
        migrate_connection_daily_manifest_generation(
            v2,
            _real_pool_gen2(),
            cutover_date="2026-08-01",  # 2026-07-27 is the only contiguous date
            new_generation_id="gen-2",
            new_rounds_url="/data/game/rounds.v1.json",
            days=5,
            generated_at="2026-07-23T00:00:00+00:00",
            existing_generation_rounds={"gen-1": gen1_pool},
        )


def test_migration_accepts_a_cutover_date_within_the_existing_schedule() -> None:
    """A cutover partway through the currently-scheduled window is valid
    and contiguous by construction (kept = dates strictly before cutover,
    new entries start exactly at cutover) -- only a cutover date further
    out than that, leaving an actual gap, is refused."""
    v2, gen1_pool = _v2_manifest(days=5)  # schedules 2026-07-22 .. 2026-07-26
    migrated = migrate_connection_daily_manifest_generation(
        v2,
        _real_pool_gen2(),
        cutover_date="2026-07-25",  # replaces 07-25, 07-26 only
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=5,
        generated_at="2026-07-20T00:00:00+00:00",
        existing_generation_rounds={"gen-1": gen1_pool},
    )
    kept_dates = [e["date"] for e in migrated["schedule"] if e["generation"] == "gen-1"]
    assert kept_dates == ["2026-07-22", "2026-07-23", "2026-07-24"]


def test_migration_rejects_a_reused_generation_id() -> None:
    v2, gen1_pool = _v2_manifest(days=5)
    with pytest.raises(ConnectionDailyManifestError, match="already exists"):
        migrate_connection_daily_manifest_generation(
            v2,
            _real_pool_gen2(),
            cutover_date="2026-07-27",
            new_generation_id="gen-1",  # reused
            new_rounds_url="/data/game/rounds.v1.json",
            days=5,
            generated_at="2026-07-23T00:00:00+00:00",
            existing_generation_rounds={"gen-1": gen1_pool},
        )


def test_migration_rejects_a_kept_entry_with_no_supplied_rounds_artifact() -> None:
    v2, _gen1_pool = _v2_manifest(days=5)
    with pytest.raises(ConnectionDailyManifestError, match="no rounds artifact"):
        migrate_connection_daily_manifest_generation(
            v2,
            _real_pool_gen2(),
            cutover_date="2026-07-27",
            new_generation_id="gen-2",
            new_rounds_url="/data/game/rounds.v1.json",
            days=5,
            generated_at="2026-07-23T00:00:00+00:00",
            existing_generation_rounds={},  # gen-1 missing
        )


def test_migration_rejects_a_kept_entry_whose_round_silently_changed() -> None:
    v2, gen1_pool = _v2_manifest(days=5)
    tampered_pool = deepcopy(gen1_pool)
    tampered_pool["rounds"][0]["answer_set"][0]["name"] = "Tampered"
    with pytest.raises(ConnectionDailyManifestError, match="fingerprint mismatch"):
        migrate_connection_daily_manifest_generation(
            v2,
            _real_pool_gen2(),
            cutover_date="2026-07-27",
            new_generation_id="gen-2",
            new_rounds_url="/data/game/rounds.v1.json",
            days=5,
            generated_at="2026-07-23T00:00:00+00:00",
            existing_generation_rounds={"gen-1": tampered_pool},
        )


def test_migration_that_empties_the_kept_schedule_still_works() -> None:
    """cutover on/before the very first scheduled date replaces everything --
    a legitimate, if extreme, case (e.g. migrating before any date was ever
    reached)."""
    v2, gen1_pool = _v2_manifest(days=5)
    migrated = migrate_connection_daily_manifest_generation(
        v2,
        _real_pool_gen2(),
        cutover_date=v2["schedule"][0]["date"],
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=5,
        generated_at="2026-07-20T00:00:00+00:00",  # 2 full days before the cutover
        existing_generation_rounds={"gen-1": gen1_pool},
    )
    assert all(e["generation"] == "gen-2" for e in migrated["schedule"])


def test_migration_is_deterministic() -> None:
    v2, gen1_pool = _v2_manifest(days=5)
    kwargs: dict[str, Any] = dict(
        cutover_date="2026-07-27",
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=5,
        generated_at="2026-07-23T00:00:00+00:00",
        existing_generation_rounds={"gen-1": gen1_pool},
    )
    first = migrate_connection_daily_manifest_generation(v2, _real_pool_gen2(), **kwargs)
    second = migrate_connection_daily_manifest_generation(v2, _real_pool_gen2(), **kwargs)
    assert first == second


# --- validate_connection_daily_manifest_v2 ----------------------------------


def test_validator_accepts_a_freshly_upgraded_manifest() -> None:
    v1 = _v1_manifest()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    validate_connection_daily_manifest_v2(v2, {"gen-1": _real_pool()})  # does not raise


def test_validator_accepts_a_migrated_two_generation_manifest() -> None:
    v2, gen1_pool = _v2_manifest(days=5)
    gen2_pool = _real_pool_gen2()
    migrated = migrate_connection_daily_manifest_generation(
        v2,
        gen2_pool,
        cutover_date="2026-07-27",
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=5,
        generated_at="2026-07-23T00:00:00+00:00",
        existing_generation_rounds={"gen-1": gen1_pool},
    )
    validate_connection_daily_manifest_v2(
        migrated, {"gen-1": gen1_pool, "gen-2": gen2_pool}
    )  # does not raise


def test_validator_rejects_a_schedule_entry_naming_an_unknown_generation() -> None:
    v1 = _v1_manifest()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    v2["schedule"][0]["generation"] = "gen-nonexistent"
    with pytest.raises(ConnectionDailyManifestError, match="not in this manifest"):
        validate_connection_daily_manifest_v2(v2, {"gen-1": _real_pool()})


def test_validator_rejects_a_round_id_reused_across_generations() -> None:
    """Cross-generation uniqueness: the same content-derived round id under
    two different generations would make 'generation' an ambiguous lookup
    key for that id."""
    v2, gen1_pool = _v2_manifest(days=5)
    gen2_pool = _real_pool_gen2()
    # Force a collision: reuse gen-1's first round id inside gen-2's pool.
    gen2_pool["rounds"][0]["id"] = v2["schedule"][0]["round_id"]
    migrated = migrate_connection_daily_manifest_generation(
        v2,
        gen2_pool,
        cutover_date="2026-07-27",
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=5,
        generated_at="2026-07-23T00:00:00+00:00",
        existing_generation_rounds={"gen-1": gen1_pool},
    )
    # Manually inject a schedule entry that reuses gen-1's round id under gen-2.
    migrated["schedule"].append(
        {
            "date": "2026-08-10",
            "round_id": v2["schedule"][0]["round_id"],
            "round_fingerprint": v2["schedule"][0]["round_fingerprint"],
            "generation": "gen-2",
        }
    )
    with pytest.raises(ConnectionDailyManifestError, match="more than once across generations"):
        validate_connection_daily_manifest_v2(migrated, {"gen-1": gen1_pool, "gen-2": gen2_pool})


def test_validator_rejects_missing_generations_array() -> None:
    v1 = _v1_manifest()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    v2["generations"] = []
    with pytest.raises(ConnectionDailyManifestError, match="non-empty array"):
        validate_connection_daily_manifest_v2(v2, {"gen-1": _real_pool()})


def test_validator_rejects_duplicate_generation_ids() -> None:
    v1 = _v1_manifest()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    v2["generations"].append(dict(v2["generations"][0]))
    with pytest.raises(ConnectionDailyManifestError, match="duplicate generation_id"):
        validate_connection_daily_manifest_v2(v2, {"gen-1": _real_pool()})


def test_validator_rejects_a_content_change_to_a_frozen_generation() -> None:
    v1 = _v1_manifest()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    tampered_pool = deepcopy(_real_pool())
    tampered_pool["rounds"][0]["answer_set"][0]["name"] = "Tampered"
    with pytest.raises(ConnectionDailyManifestError, match="fingerprint mismatch"):
        validate_connection_daily_manifest_v2(v2, {"gen-1": tampered_pool})


def test_validator_rejects_a_generation_entry_whose_versions_dont_match_its_artifact() -> None:
    """Real Codex finding: schema v1's `_version_mismatches` guarantee -- the
    manifest's claimed catalog/pool/artifact versions must match the actual
    artifact used to verify it -- was only checked per schedule-entry
    fingerprint, never against `generations[]`'s own version fields. A
    hand-edited generation entry (or a validator call given the wrong rounds
    artifact for that generation_id) that still contains the right round ids
    would otherwise pass silently."""
    v1 = _v1_manifest()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    v2["generations"][0]["catalog_version"] = "catalog-v1-20260601-tampered"
    with pytest.raises(ConnectionDailyManifestError, match="does not match"):
        validate_connection_daily_manifest_v2(v2, {"gen-1": _real_pool()})


def test_validator_rejects_a_nested_seed_key() -> None:
    v1 = _v1_manifest()
    v2 = upgrade_connection_daily_manifest_to_v2(
        v1, generation_id="gen-1", rounds_url="/data/game/generations/gen-1/rounds.json"
    )
    v2["generations"][0]["seed"] = "leak"
    with pytest.raises(ConnectionDailyManifestError, match="must not have a 'seed' key"):
        validate_connection_daily_manifest_v2(v2, {"gen-1": _real_pool()})


def test_migration_never_reschedules_a_round_id_already_used_by_a_kept_generation() -> None:
    """Real bug hit on the actual Phase 7 gen-1 -> gen-2 cutover: round ids
    are CONTENT-derived, so a regenerated pool legitimately contains rounds
    byte-identical to ones the kept schedule already uses (same album pair,
    same answer set => same id). Scheduling one again under the new
    generation puts a single id on two dates under two generations --
    rejected by validate_connection_daily_manifest_v2, and a repeat of a
    round visitors already played. The real migration failed with six such
    collisions before this filter existed.
    """
    v2, gen1_pool = _v2_manifest(days=5)
    kept_round_ids = {e["round_id"] for e in v2["schedule"][:3]}
    assert kept_round_ids  # fixture sanity

    # gen-2's pool deliberately REUSES gen-1's exact rounds (content-identical
    # regeneration) plus fresh ones, reproducing the real collision shape.
    gen2_pool = _real_pool_gen2()
    gen2_pool["rounds"] = deepcopy(gen1_pool["rounds"]) + gen2_pool["rounds"]

    migrated = migrate_connection_daily_manifest_generation(
        v2,
        gen2_pool,
        cutover_date=v2["schedule"][3]["date"],
        new_generation_id="gen-2",
        new_rounds_url="/data/game/rounds.v1.json",
        days=5,
        generated_at="2026-07-20T00:00:00+00:00",
        existing_generation_rounds={"gen-1": gen1_pool},
    )

    new_entries = [e for e in migrated["schedule"] if e["generation"] == "gen-2"]
    assert new_entries, "expected the migration to schedule at least one gen-2 date"
    assert not ({e["round_id"] for e in new_entries} & kept_round_ids), (
        "a gen-2 date reused a round id already scheduled under gen-1"
    )
    # And the whole manifest still validates against both pools.
    validate_connection_daily_manifest_v2(migrated, {"gen-1": gen1_pool, "gen-2": gen2_pool})
