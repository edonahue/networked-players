"""The round seed spec (`data/rounds/round-<n>-seed-spec-v1.json`, Campaign Atlas SS).

A committed, PUBLIC declaration of what an expansion round is seeded from: its
themes (a name, seed artist ids and/or seed master ids, optional Discogs
style/genre tags, optional decade bounds), the lane shares and the target
count (ADR 0072 section 7). Naming a theme approves no album; this file feeds
the supply stage (`build-theme-candidates`), whose output is private and never
authorises publication -- the approved pool does.

Not to be confused with the round RUNNER's spec (`data/contracts/round-spec-v1.md`),
which wires paths and policy inputs. That one says how to rebuild; this one says
what to look for.

Only public Discogs ids and editorial labels belong here: no collection
membership, no scores, no reviewer identity. Unknown keys are rejected so the
file cannot quietly grow private fields.

Pure Python and dependency-free (runs on 1 GB Raspberry Pi workers).
"""

from __future__ import annotations

from typing import Any, TypeGuard

ROUND_SEED_SPEC_SCHEMA_VERSION = 1
LANES = ("theme", "graph_value", "coverage_repair")

_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "round", "target_count", "lane_shares_percent", "themes", "note"}
)
_THEME_KEYS = frozenset(
    {
        "name",
        "seed_artist_ids",
        "seed_master_ids",
        "styles",
        "genres",
        "year_min",
        "year_max",
        "min_shared_performers",
        "candidate_cap",
    }
)
MAX_CANDIDATE_CAP = 5000
MAX_SEEDS_PER_THEME = 500


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_int_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_int(v) and v > 0 for v in value)


def _theme_failures(index: int, theme: Any) -> list[str]:
    at = f"themes[{index}]"
    if not isinstance(theme, dict):
        return [f"{at} must be an object"]
    failures: list[str] = []
    extra = sorted(set(theme) - _THEME_KEYS)
    if extra:
        failures.append(f"{at} has unexpected keys: {extra}")
    name = theme.get("name")
    if not isinstance(name, str) or not name.strip():
        failures.append(f"{at}.name must be a non-empty string")
    elif name != name.strip():
        failures.append(f"{at}.name must not have leading or trailing whitespace")
    artists = theme.get("seed_artist_ids", [])
    masters = theme.get("seed_master_ids", [])
    if not _positive_int_list(artists):
        failures.append(f"{at}.seed_artist_ids must be a list of positive integers")
        artists = []
    if not _positive_int_list(masters):
        failures.append(f"{at}.seed_master_ids must be a list of positive integers")
        masters = []
    for key, ids in (("seed_artist_ids", artists), ("seed_master_ids", masters)):
        if len(ids) != len(set(ids)):
            failures.append(f"{at}.{key} contains a duplicate id")
        if len(ids) > MAX_SEEDS_PER_THEME:
            failures.append(f"{at}.{key} has more than {MAX_SEEDS_PER_THEME} ids")
    if not artists and not masters:
        failures.append(f"{at} needs at least one seed artist id or seed master id")
    for key in ("styles", "genres"):
        tags = theme.get(key, [])
        if not isinstance(tags, list) or not all(isinstance(t, str) and t.strip() for t in tags):
            failures.append(f"{at}.{key} must be a list of non-empty strings")
        elif len(tags) != len(set(tags)):
            failures.append(f"{at}.{key} contains a duplicate tag")
    lo, hi = theme.get("year_min"), theme.get("year_max")
    for key, value in (("year_min", lo), ("year_max", hi)):
        if value is not None and not (_is_int(value) and 1900 <= value <= 2100):
            failures.append(f"{at}.{key} must be null or an integer year in 1900..2100")
    if _is_int(lo) and _is_int(hi) and lo > hi:
        failures.append(f"{at}.year_min must not exceed year_max")
    shared = theme.get("min_shared_performers")
    if not _is_int(shared) or not 1 <= shared <= 20:
        failures.append(
            f"{at}.min_shared_performers must be an integer in 1..20 (stated, no default)"
        )
    cap = theme.get("candidate_cap")
    if not _is_int(cap) or not 1 <= cap <= MAX_CANDIDATE_CAP:
        failures.append(
            f"{at}.candidate_cap must be an integer in 1..{MAX_CANDIDATE_CAP} (stated, no default)"
        )
    return failures


def round_seed_spec_failures(spec: Any) -> list[str]:
    """Shape failures of a round seed spec. Empty list means valid."""
    if not isinstance(spec, dict):
        return ["round seed spec must be a JSON object"]
    failures: list[str] = []
    extra = sorted(set(spec) - _TOP_LEVEL_KEYS)
    if extra:
        failures.append(f"round seed spec has unexpected top-level keys: {extra}")
    if spec.get("schema_version") != ROUND_SEED_SPEC_SCHEMA_VERSION:
        failures.append(f"schema_version must be {ROUND_SEED_SPEC_SCHEMA_VERSION}")
    for key in ("round", "target_count"):
        if not _is_int(spec.get(key)) or spec[key] < 1:
            failures.append(f"{key} must be a positive integer")
    if not isinstance(spec.get("note"), str) or not spec["note"].strip():
        failures.append("note must be a non-empty string")

    shares = spec.get("lane_shares_percent")
    if not isinstance(shares, dict) or set(shares) != set(LANES):
        failures.append(f"lane_shares_percent must have exactly the keys {list(LANES)}")
    elif not all(_is_int(v) and v >= 0 for v in shares.values()):
        failures.append("lane_shares_percent values must be non-negative integers")
    elif sum(shares.values()) != 100:
        failures.append(f"lane_shares_percent must sum to 100, got {sum(shares.values())}")

    themes = spec.get("themes")
    if not isinstance(themes, list) or not themes:
        failures.append("themes must be a non-empty list")
    else:
        for index, theme in enumerate(themes):
            failures += _theme_failures(index, theme)
        names = [
            t["name"].strip().casefold()
            for t in themes
            if isinstance(t, dict) and isinstance(t.get("name"), str)
        ]
        if len(names) != len(set(names)):
            failures.append("theme names must be unique")
    return failures


def lane_quotas(spec: dict[str, Any]) -> dict[str, int]:
    """Whole-album lane quotas from the shares, by largest remainder (ties to the
    earlier lane), summing exactly to `target_count`. Call on a valid spec."""
    target = int(spec["target_count"])
    shares = spec["lane_shares_percent"]
    base = {lane: target * int(shares[lane]) // 100 for lane in LANES}
    remainders = sorted(
        LANES, key=lambda lane: (-(target * int(shares[lane]) % 100), LANES.index(lane))
    )
    for lane in remainders[: target - sum(base.values())]:
        base[lane] += 1
    return base
