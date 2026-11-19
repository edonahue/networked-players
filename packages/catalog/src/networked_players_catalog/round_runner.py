"""The round runner (ADR 0072 section 3, Campaign Atlas F3): `networked-players-catalog round`.

Rebuilding the public artifacts for a catalog round is a fixed sequence of
existing builders with many flags. Round 1 failed in several ways that were all
ordering or flag mistakes (a builder skipped, a code default used instead of the
published value, the challenge rebuilt without carrying the previous one
forward, the Connection Guesser pool regenerated while the live daily-manifest
generation still pointed at that file). This module makes the order and the
preconditions executable. It is a thin orchestrator: every stage calls the same
`cli.main([...])` entry point the matching subcommand uses; no builder logic is
duplicated here.

Operator-run only. It must never be wired into CI or `make check`: the album-art
stage needs a Discogs API token and a private cache. There is deliberately no
content-addressed stage cache (ADR 0072 section 3), and the daily-manifest
stages are calendar-coupled, so they are never skipped as "unchanged".

Layout assumed by the spec (see `data/contracts/round-spec-v1.md`):

- `previous_artifacts_dir` (P): a read-only snapshot of the currently published
  `apps/web/public/data` (e.g. `git archive HEAD apps/web/public/data`). It is
  the carry-forward / inheritance / continuity baseline. The runner refuses to
  run when it equals the output directory, because the baseline would be
  destroyed by the first stage.
- `output_dir` (O): where stages write. The real target is
  `apps/web/public/data`; tests use a temp dir.
- `work_dir` (W): git-ignored scratch for `stage-results.json` and
  `report.md`; never under the public tree.

Stdlib-only apart from the repo's own packages, like the rest of the catalog
CLI. No timing or memory figures are ever printed or recorded (ADR 0018).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

from networked_players_contracts.artifact_lineage import (
    VERSION_FIELD_PATHS,
    artifact_content_version,
)

from .build_parameters import (
    CHALLENGE_DEFAULT_BUILD_PARAMETERS,
    CONNECTION_ROUNDS_DEFAULT_BUILD_PARAMETERS,
    RECORD_ROUTES_DEFAULT_BUILD_PARAMETERS,
    BuildParametersError,
    read_previous_build_parameters,
    resolve_build_parameters,
)

SPEC_SCHEMA_VERSION = 1

# Published layout under `apps/web/public/data/`, relative.
CATALOG = "catalog/albums.v1.json"
ART = "catalog/album-art.v1.json"
MEMBERSHIP = "albums/credit-membership.v1.json"
GRAPH = "pathfinding/graph.v4.json"
PROMINENCE = "pathfinding/prominence.v1.json"
CHALLENGE = "challenge.v3.json"
ROUTES_UNIVERSE = "routes/universe.v1.json"
ROUTES_ROUNDS = "routes/rounds.v1.json"
GAME_UNIVERSE = "game/universe.v1.json"
GAME_ROUNDS = "game/rounds.v1.json"
DAILY_MANIFEST = "game/daily-manifest.v1.json"
EVIDENCE = "evidence/release-registry.v1.json"
CONTRIBUTORS = "contributors/index.v1.json"
HOP_DISTANCES = "contributors/album-hop-distances.v1.json"
SEARCH = "search/index.v1.json"

# The URL the newest daily-manifest generation points at: the live rounds file
# the connection-rounds stage overwrites (ADR 0066).
LIVE_ROUNDS_URL = "/data/" + GAME_ROUNDS

# artifact name (artifact_lineage) -> published path of the file carrying its version.
ARTIFACT_PATHS: dict[str, str] = {
    "catalog": CATALOG,
    "album_art_registry": ART,
    "album_credit_membership": MEMBERSHIP,
    "pathfinding_graph": GRAPH,
    "challenge": CHALLENGE,
    "record_routes": ROUTES_UNIVERSE,
    "connection_guesser": GAME_UNIVERSE,
    "evidence_release_registry": EVIDENCE,
    "prominence": PROMINENCE,
    "contributor_index": CONTRIBUTORS,
    "search_index": SEARCH,
    "album_hop_distances": HOP_DISTANCES,
}
assert set(ARTIFACT_PATHS) == set(VERSION_FIELD_PATHS)

# Every file a round writes that Prettier may format (before the ignore filter).
FORMATTABLE = (*ARTIFACT_PATHS.values(), ROUTES_ROUNDS, GAME_ROUNDS, DAILY_MANIFEST)

# Spec inputs: name -> (kind, required_by). `required_by` names the builder that
# cannot run without it; for those a `null` + reason is a valid spec but fails
# planning with a message naming the builder. Everything else is genuinely
# optional, but still must be stated explicitly (path, or null + reason).
INPUT_SPECS: dict[str, tuple[str, str | None]] = {
    "onehop_root": ("dir", "every builder"),
    "masters_root": ("dir", "build-public-album-catalog"),
    "release_format_policy": ("file", "build-public-album-catalog"),
    "studio_album_exclusions": ("file", "build-public-album-catalog"),
    "candidates": ("file", "build-public-album-catalog"),
    "approved_pool": ("file", "round verify (validate-public-artifacts has no pool-less mode)"),
    # The pin over already-played daily dates and the payload budgets are
    # read by `validate-public-artifacts`. They are explicit round inputs so
    # the verify stage checks THIS round's output against them instead of
    # silently falling back to the repository's committed defaults.
    "daily_manifest_pin": ("file", "round verify (played daily dates must not change)"),
    "payload_budgets": ("file", "round verify (payload-size budgets)"),
    "artist_family_exclusions": ("file", None),
    "featured_albums": ("file", None),
    "editorial_albums": ("file", None),
    "personal_seed": ("file", None),
    "graph_rich_selection": ("file", None),
    "coverage_gap_candidates": ("file", None),
    "album_art_cache_dir": ("dir", None),
    # Seed supply and post-approval re-widen (Campaign Atlas SS). Stated in every
    # spec, but only enforced when a selected stage needs them (INPUT_STAGES).
    "round_seed_spec": ("file", "theme-supply"),
    "full_corpus_root": ("dir", "theme-supply and onehop-rewiden"),
    "private_seed": ("file", "onehop-rewiden"),
    "editorial_seed": ("file", "onehop-rewiden"),
}
# Inputs enforced (non-null, existing) only when one of these stages is selected.
INPUT_STAGES: dict[str, frozenset[str]] = {
    "round_seed_spec": frozenset({"theme-supply"}),
    "full_corpus_root": frozenset({"theme-supply", "onehop-rewiden"}),
    "private_seed": frozenset({"onehop-rewiden"}),
    "editorial_seed": frozenset({"onehop-rewiden"}),
}
THEME_CANDIDATES = "theme-candidates.json"  # under work_dir (git-ignored)
THEME_DIAGNOSTICS = "theme-candidates-diagnostics.json"  # ineligible rows + summaries
THEME_FORMAT_INDEX = "theme-release-format-index.json"  # merged index: the scorer's policy
REWIDEN_SEED = "rewiden-seed.json"  # under work_dir (git-ignored)

PARAMETER_KEYS: dict[str, tuple[str, ...]] = {
    "challenge": tuple(CHALLENGE_DEFAULT_BUILD_PARAMETERS),
    "record_routes": tuple(RECORD_ROUTES_DEFAULT_BUILD_PARAMETERS),
    "connection_rounds": tuple(CONNECTION_ROUNDS_DEFAULT_BUILD_PARAMETERS),
}
PARAMETER_FLAGS = {
    "max_hops": "--max-hops",
    "max_frontier_expansion": "--max-frontier-expansion",
    "one_hop_target": "--one-hop-target",
    "two_hop_target": "--two-hop-target",
    "max_endpoint_share": "--max-endpoint-share",
    "max_bridge_share": "--max-bridge-share",
}
PARAMETER_DEFAULTS: dict[str, dict[str, Any]] = {
    "challenge": CHALLENGE_DEFAULT_BUILD_PARAMETERS,
    "record_routes": RECORD_ROUTES_DEFAULT_BUILD_PARAMETERS,
    "connection_rounds": CONNECTION_ROUNDS_DEFAULT_BUILD_PARAMETERS,
}
# Where each builder's previous artifact (the inheritance source) lives.
PARAMETER_PREVIOUS = {
    "challenge": (CHALLENGE, "--carry-forward-challenge"),
    "record_routes": (ROUTES_UNIVERSE, "--previous-routes-universe"),
    "connection_rounds": (GAME_UNIVERSE, "--previous-connection-universe"),
}


class RoundError(RuntimeError):
    """A round-runner failure that is the operator's to fix (bad spec, failed
    precondition, failed stage)."""


class StageFailure(RoundError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"stage {stage!r} failed: {message}")
        self.stage = stage


Formatter = Callable[[list[Path]], None]
# (ctx) -> None; must write the album-art registry at ctx.o(ART).
ArtBuilder = Callable[["Ctx"], None]


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def _is_iso_date(value: Any) -> bool:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def _is_iso_datetime_with_tz(value: Any) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except (TypeError, ValueError):
        return False


def validate_spec_shape(spec: Any) -> list[str]:
    """Structural validation only (no filesystem). Returns failures."""
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    failures: list[str] = []
    if spec.get("schema_version") != SPEC_SCHEMA_VERSION:
        failures.append(f"schema_version must be {SPEC_SCHEMA_VERSION}")
    for key in ("round", "target_count"):
        value = spec.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            failures.append(f"{key} must be a positive integer")
    themes = spec.get("themes")
    if not isinstance(themes, list) or not all(isinstance(t, str) and t for t in themes):
        failures.append("themes must be a list of non-empty label strings")
    if not _is_iso_datetime_with_tz(spec.get("generated_at")):
        failures.append("generated_at must be an explicit ISO datetime with a UTC offset")
    if not _is_iso_date(spec.get("planned_merge_date")):
        failures.append("planned_merge_date must be an ISO date (YYYY-MM-DD)")
    daily = spec.get("daily")
    if not isinstance(daily, dict):
        failures.append("daily must be an object")
    else:
        lead = daily.get("cutover_lead_days")
        if not isinstance(lead, int) or isinstance(lead, bool) or lead < 1:
            failures.append("daily.cutover_lead_days must be an integer >= 1")
        days = daily.get("days")
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            failures.append("daily.days must be a positive integer")
        generation_id = daily.get("new_generation_id")
        if not isinstance(generation_id, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]+", generation_id
        ):
            failures.append("daily.new_generation_id must be a simple id such as 'gen-4'")
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        failures.append("paths must be an object")
    else:
        for key in ("previous_artifacts_dir", "output_dir", "work_dir"):
            if not isinstance(paths.get(key), str) or not paths.get(key):
                failures.append(f"paths.{key} must be a non-empty path string")
    inputs = spec.get("inputs")
    if not isinstance(inputs, dict):
        failures.append("inputs must be an object")
    else:
        for name in INPUT_SPECS:
            if name not in inputs:
                failures.append(
                    f"inputs.{name} is missing -- every input must be stated explicitly, either "
                    'a path or {"path": null, "reason": "<why this round does not use it>"}'
                )
                continue
            value = inputs[name]
            if isinstance(value, str) and value:
                continue
            if (
                isinstance(value, dict)
                and set(value) == {"path", "reason"}
                and value["path"] is None
                and isinstance(value["reason"], str)
                and value["reason"].strip()
            ):
                continue
            failures.append(
                f"inputs.{name} must be a path string or "
                '{"path": null, "reason": "<non-empty text>"}'
            )
        for name in sorted(set(inputs) - set(INPUT_SPECS)):
            failures.append(f"inputs.{name} is not a known input")
    parameters = spec.get("parameters")
    if not isinstance(parameters, dict):
        failures.append("parameters must be an object (it may be empty)")
    else:
        for builder, block in parameters.items():
            if builder not in PARAMETER_KEYS:
                failures.append(f"parameters.{builder} is not a known builder")
            elif not isinstance(block, dict):
                failures.append(f"parameters.{builder} must be an object")
            else:
                for key, value in block.items():
                    if key not in PARAMETER_KEYS[builder]:
                        failures.append(f"parameters.{builder}.{key} is not a known parameter")
                    elif value is not None and (
                        isinstance(value, bool) or not isinstance(value, int | float)
                    ):
                        failures.append(f"parameters.{builder}.{key} must be a number or null")
    return failures


def load_spec(path: Path) -> dict[str, Any]:
    try:
        spec = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RoundError(f"cannot read round spec {path}: {error}") from error
    failures = validate_spec_shape(spec)
    if failures:
        raise RoundError(
            f"round spec {path} is invalid:\n" + "\n".join(f"  - {f}" for f in failures)
        )
    assert isinstance(spec, dict)
    return spec


# ---------------------------------------------------------------------------
# Prettier ignore handling (honour apps/web/.prettierignore, never blanket-format)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB_DIR = REPO_ROOT / "apps" / "web"
PRETTIERIGNORE = WEB_DIR / ".prettierignore"
PUBLIC_DATA_PREFIX = "public/data/"


def _ignore_pattern_regex(pattern: str) -> re.Pattern[str]:
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + "(?:/.*)?")


def load_prettier_ignore(path: Path = PRETTIERIGNORE) -> list[re.Pattern[str]]:
    if not path.is_file():
        raise RoundError(f"{path} not found -- cannot tell which artifacts Prettier must skip")
    patterns = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(_ignore_pattern_regex(line.lstrip("/")))
    return patterns


def prettier_ignored(rel: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    """Whether the published artifact `rel` (relative to public/data) is ignored."""
    candidate = PUBLIC_DATA_PREFIX + rel
    return any(p.fullmatch(candidate) for p in patterns)


def default_formatter(files: list[Path]) -> None:
    """Run the repo's own Prettier over `files`; fail loudly if it is unavailable."""
    if shutil.which("node") is None:
        raise RoundError("Node is not on PATH; Prettier cannot run. Install Node, then rerun.")
    prettier = WEB_DIR / "node_modules" / ".bin" / "prettier"
    if not prettier.exists():
        raise RoundError(
            f"Prettier is not installed ({prettier} missing). Run `npm ci` in apps/web, "
            "then restart with --from-stage format."
        )
    # Prettier runs from apps/web (its config and ignore file live there), so
    # every file argument must be absolute: a spec written with repo-relative
    # paths would otherwise be looked up beneath apps/web/ and not found.
    proc = subprocess.run(
        [str(prettier), "--write", *(str(f.resolve()) for f in files)],
        cwd=WEB_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RoundError(f"prettier exited {proc.returncode}: {proc.stderr.strip()[:500]}")


def formatter_unavailable_reason() -> str | None:
    if shutil.which("node") is None:
        return "Node is not on PATH"
    if not (WEB_DIR / "node_modules" / ".bin" / "prettier").exists():
        return "Prettier is not installed (run `npm ci` in apps/web)"
    return None


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class Ctx:
    spec: dict[str, Any]
    today: date
    prev: Path
    out: Path
    work: Path
    inputs: dict[str, Path | None]
    formatter: Formatter | None = None
    art_builder: ArtBuilder | None = None
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr)
    results: dict[str, Any] = field(default_factory=dict)

    @property
    def generated_at(self) -> str:
        return str(self.spec["generated_at"])

    def o(self, rel: str) -> Path:
        return self.out / rel

    def p(self, rel: str) -> Path:
        return self.prev / rel

    def inp(self, name: str) -> Path:
        value = self.inputs[name]
        if value is None:
            raise RoundError(f"inputs.{name} is null but this stage needs it")
        return value

    def manifest_path(self) -> Path:
        """The daily manifest the next stage will act on: the output copy if it
        exists (an earlier stage or an earlier run already took the baseline),
        else the published baseline."""
        out = self.o(DAILY_MANIFEST)
        return out if out.is_file() else self.p(DAILY_MANIFEST)

    def manifest(self) -> dict[str, Any]:
        path = self.manifest_path()
        try:
            loaded = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RoundError(f"cannot read daily manifest {path}: {error}") from error
        if not isinstance(loaded, dict) or loaded.get("schema_version") != 2:
            raise RoundError(
                f"{path} is not a schema-v2 daily manifest -- run "
                "upgrade-connection-daily-manifest-to-v2 first (ADR 0066)"
            )
        return loaded


def build_ctx(
    spec: dict[str, Any],
    *,
    today: date,
    formatter: Formatter | None = None,
    art_builder: ArtBuilder | None = None,
    log: Callable[[str], None] | None = None,
) -> Ctx:
    inputs: dict[str, Path | None] = {}
    for name in INPUT_SPECS:
        value = spec["inputs"][name]
        inputs[name] = Path(value) if isinstance(value, str) else None
    ctx = Ctx(
        spec=spec,
        today=today,
        prev=Path(spec["paths"]["previous_artifacts_dir"]),
        out=Path(spec["paths"]["output_dir"]),
        work=Path(spec["paths"]["work_dir"]),
        inputs=inputs,
        formatter=formatter,
        art_builder=art_builder,
    )
    if log is not None:
        ctx.log = log
    return ctx


# ---------------------------------------------------------------------------
# Calendar and daily-manifest rules (pure)
# ---------------------------------------------------------------------------


def cutover_date(spec: dict[str, Any]) -> date:
    return date.fromisoformat(spec["planned_merge_date"]) + timedelta(
        days=int(spec["daily"]["cutover_lead_days"])
    )


def calendar_failures(spec: dict[str, Any], *, today: date) -> list[str]:
    """The migration's calendar rules, from the spec alone.

    1. The cutover is strictly after the planned merge date (a round whose PR
       merges on or after its cutover rewrites dates players have seen,
       ADR 0072 section 4).
    2. The cutover leads `generated_at` by the module's own minimum
       (`_MIN_CUTOVER_LEAD_DAYS`), exactly as
       `migrate_connection_daily_manifest_generation` will enforce.
    3. The cutover leads `--today` by the same minimum. This is stricter than
       "in the future": players' local calendars span two date labels, so a
       cutover that is merely tomorrow may already be reached somewhere.
    """
    from networked_players_graph_core.connection_daily_manifest import _MIN_CUTOVER_LEAD_DAYS

    cutover = cutover_date(spec)
    merge = date.fromisoformat(spec["planned_merge_date"])
    generated = datetime.fromisoformat(spec["generated_at"]).astimezone(UTC).date()
    failures: list[str] = []
    if cutover <= merge:
        failures.append(
            f"cutover {cutover} is not after the planned merge date {merge}; raise "
            "daily.cutover_lead_days"
        )
    if merge < today:
        failures.append(
            f"planned_merge_date {merge} is before --today {today}; update the spec to the "
            "real merge date"
        )
    if cutover < generated + timedelta(days=_MIN_CUTOVER_LEAD_DAYS):
        failures.append(
            f"cutover {cutover} is less than {_MIN_CUTOVER_LEAD_DAYS} days after generated_at "
            f"{generated}; the migration will refuse it"
        )
    if cutover < today + timedelta(days=_MIN_CUTOVER_LEAD_DAYS):
        failures.append(
            f"cutover {cutover} is not at least {_MIN_CUTOVER_LEAD_DAYS} days in the future of "
            f"--today {today}; a date players may already have reached cannot be rewritten "
            "(ADR 0072 section 4). Move the merge date, or rebuild after the cutover has passed "
            "and schedule forward"
        )
    return failures


def live_generation_ids(manifest: dict[str, Any]) -> list[str]:
    return [
        str(g["generation_id"])
        for g in manifest.get("generations", [])
        if g.get("rounds_url") == LIVE_ROUNDS_URL
    ]


def manifest_calendar_failures(manifest: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """Manifest-dependent migration rules, checked before any builder runs."""
    failures: list[str] = []
    generation_id = spec["daily"]["new_generation_id"]
    if generation_id in {g["generation_id"] for g in manifest.get("generations", [])}:
        failures.append(
            f"daily.new_generation_id {generation_id!r} already exists in the manifest "
            "(generations are append-only and never reused)"
        )
    schedule = manifest.get("schedule") or []
    if schedule:
        cutover = cutover_date(spec)
        first = date.fromisoformat(schedule[0]["date"])
        last = date.fromisoformat(schedule[-1]["date"])
        if cutover > last + timedelta(days=1):
            failures.append(
                f"cutover {cutover} would leave a gap after the last scheduled date {last}; "
                "the published schedule must stay contiguous. Lower daily.cutover_lead_days or "
                "extend the manifest first"
            )
        if cutover <= first:
            failures.append(f"cutover {cutover} is not after the manifest's first date {first}")
    return failures


def newest_generation_cutover(manifest: dict[str, Any]) -> str | None:
    """First scheduled date of the newest generation (its cutover date)."""
    generations = manifest.get("generations") or []
    if not generations:
        return None
    newest = generations[-1]["generation_id"]
    dates = [e["date"] for e in manifest.get("schedule", []) if e.get("generation") == newest]
    return min(dates) if dates else None


def cutover_still_future_failures(manifest: Any, *, today: str) -> list[str]:
    """CI-safe, pure check for a round PR: the newest generation's cutover date
    must be strictly after `today`. Valid only at PR time -- on a manifest whose
    last round has long since merged the cutover is legitimately in the past, so
    this is never part of `validate-public-artifacts`. A round PR invokes it as
    `networked-players-catalog round check-cutover --manifest <path> --today <date>`."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["daily manifest is not schema v2"]
    if not _is_iso_date(today):
        return [f"--today {today!r} is not an ISO date"]
    cutover = newest_generation_cutover(manifest)
    if cutover is None:
        return ["daily manifest has no generation with scheduled dates"]
    if date.fromisoformat(cutover) <= date.fromisoformat(today):
        return [
            f"newest generation's cutover date {cutover} is not after {today}: dates players "
            "may already have seen would be rewritten. Do not merge this round; rebuild with a "
            "later cutover (ADR 0072 section 4)"
        ]
    return []


def daily_manifest_continuity_failures(
    previous: dict[str, Any], current: dict[str, Any], *, today: date
) -> list[str]:
    """No already-played date changed relative to the previous manifest.

    Entries dated before the new generation's cutover, and any entry dated on or
    before `today`, must be byte-for-byte the previous entries; `generations[]`
    is append-only (only `rounds_url` of a frozen generation may change).
    """
    failures: list[str] = []
    prev_gens = previous.get("generations") or []
    cur_gens = current.get("generations") or []
    if [g["generation_id"] for g in cur_gens[: len(prev_gens)]] != [
        g["generation_id"] for g in prev_gens
    ]:
        failures.append("generations[] is not an append-only extension of the previous manifest")
    for before, after in zip(prev_gens, cur_gens, strict=False):
        for key in ("catalog_version", "pool_version", "artifact_version"):
            if before.get(key) != after.get(key):
                failures.append(
                    f"generation {before['generation_id']!r} changed its pinned {key}; a "
                    "generation's identity is immutable"
                )
    cutover = newest_generation_cutover(current) if len(cur_gens) > len(prev_gens) else None
    current_by_date = {e["date"]: e for e in current.get("schedule", [])}
    for entry in previous.get("schedule", []):
        played = date.fromisoformat(entry["date"]) <= today
        before_cutover = cutover is not None and entry["date"] < cutover
        if cutover is None or played or before_cutover:
            if current_by_date.get(entry["date"]) != entry:
                failures.append(
                    f"scheduled date {entry['date']} changed relative to the previous manifest, "
                    "but it is "
                    + ("already played/today" if played else "before the cutover")
                    + " -- never rewrite it (ADR 0041/0066)"
                )
    dates = [e["date"] for e in current.get("schedule", [])]
    if dates != sorted(set(dates)):
        failures.append("schedule dates are not strictly increasing and unique")
    return failures


# ---------------------------------------------------------------------------
# Parameter resolution (inherited from the previous artifacts)
# ---------------------------------------------------------------------------


def resolve_parameters(ctx: Ctx) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """{builder: {param: {"value", "source"}}} and failures.

    The `build_parameters` blocks are read from the PREVIOUS published artifacts
    with the same helpers the builders use. A value that would fall back to a
    code default is a failure: Round 1's halved two-hop pool was exactly that.
    """
    resolved: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for builder, (rel, flag) in PARAMETER_PREVIOUS.items():
        supplied = {
            k: v for k, v in (ctx.spec["parameters"].get(builder) or {}).items() if v is not None
        }
        previous_block = None
        path = ctx.p(rel)
        if path.is_file():
            try:
                previous_block = read_previous_build_parameters(
                    json.loads(path.read_text()), flag=flag, at="provenance"
                )
            except (BuildParametersError, json.JSONDecodeError) as error:
                failures.append(f"{builder}: {error}")
                continue
        table = resolve_build_parameters(
            supplied=supplied, previous=previous_block, defaults=PARAMETER_DEFAULTS[builder]
        )
        resolved[builder] = {
            name: {"value": r.value, "source": "explicit" if r.source == "cli" else r.source}
            for name, r in table.items()
        }
        for name, entry in resolved[builder].items():
            if entry["source"] == "default":
                failures.append(
                    f"{builder}.{name} would use the code default {entry['value']!r}: the "
                    f"previous {rel} records no build_parameters for it. Set "
                    f"parameters.{builder}.{name} in the spec to the value the published "
                    "artifact actually has (Round 1 shipped a halved two-hop pool this way)"
                )
    return resolved, failures


def _parameter_flags(ctx: Ctx, builder: str) -> list[str]:
    argv: list[str] = []
    for key in PARAMETER_KEYS[builder]:
        value = (ctx.spec["parameters"].get(builder) or {}).get(key)
        if value is not None:
            argv += [PARAMETER_FLAGS[key], str(value)]
    return argv


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    name: str
    command: str
    summary: str
    reads: str
    writes: tuple[str, ...]
    argv: Callable[[Ctx], list[list[str]]]
    execute: Callable[[Ctx, Stage], None] | None = None  # None: run argv through cli.main
    precheck: Callable[[Ctx, bool], list[str]] | None = None  # (ctx, planning) -> failures
    # Opt-in stages sit outside the default publish sequence (they straddle human review
    # steps or need a workstation); they run only when a selection names them.
    opt_in: bool = False


def _optional(ctx: Ctx, name: str, flag: str) -> list[str]:
    path = ctx.inputs[name]
    return [flag, str(path)] if path is not None else []


def _argv_prepare(ctx: Ctx) -> list[list[str]]:
    return []


def _argv_catalog(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-public-album-catalog",
            "--onehop-root", str(ctx.inp("onehop_root")),
            "--approved-pool", str(ctx.inp("approved_pool")),
            "--already-published-catalog", str(ctx.p(CATALOG)),
            *_optional(ctx, "editorial_albums", "--editorial-albums"),
            *_optional(ctx, "personal_seed", "--personal-seed"),
            *_optional(ctx, "graph_rich_selection", "--graph-rich-selection"),
            *_optional(ctx, "coverage_gap_candidates", "--coverage-gap-candidates"),
            *_optional(ctx, "featured_albums", "--featured-albums"),
            "--candidates", str(ctx.inp("candidates")),
            "--target-count", str(ctx.spec["target_count"]),
            "--expansion-round", str(ctx.spec["round"]),
            "--release-format-policy", str(ctx.inp("release_format_policy")),
            "--masters-root", str(ctx.inp("masters_root")),
            "--studio-album-exclusions", str(ctx.inp("studio_album_exclusions")),
            "--output", str(ctx.o(CATALOG)),
        ]
    ]  # fmt: skip


def _argv_membership(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-album-credit-membership",
            "--onehop-root", str(ctx.inp("onehop_root")),
            "--catalog", str(ctx.o(CATALOG)),
            "--output", str(ctx.o(MEMBERSHIP)),
            "--generated-at", ctx.generated_at,
        ]
    ]  # fmt: skip


def _argv_graph(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-pathfinding-graph",
            "--onehop-root", str(ctx.inp("onehop_root")),
            "--catalog", str(ctx.o(CATALOG)),
            "--album-credit-membership", str(ctx.o(MEMBERSHIP)),
            "--output", str(ctx.o(GRAPH)),
            "--generated-at", ctx.generated_at,
        ]
    ]  # fmt: skip


def _argv_challenge(ctx: Ctx) -> list[list[str]]:
    # `--albums` is passed explicitly: the code default is data/albums/top-albums-v1.json,
    # which the runbook's step 12 never overrode (it would build the wrong album set).
    return [
        [
            "build-challenge-from-dump",
            "--onehop-root", str(ctx.inp("onehop_root")),
            "--albums", str(ctx.o(CATALOG)),
            "--masters-root", str(ctx.inp("masters_root")),
            "--release-format-policy", str(ctx.inp("release_format_policy")),
            "--studio-album-exclusions", str(ctx.inp("studio_album_exclusions")),
            *_optional(ctx, "artist_family_exclusions", "--artist-family-exclusions"),
            "--carry-forward-challenge", str(ctx.p(CHALLENGE)),
            "--in-memory-search",
            # G1b: fail the stage if any published hop is not an edge of THIS round's graph
            # (the graph stage runs first). Opt-in on the CLI, always on for new rounds.
            "--verify-hops-against-graph", str(ctx.o(GRAPH)),
            *_parameter_flags(ctx, "challenge"),
            "--output", str(ctx.o(CHALLENGE)),
        ]
    ]  # fmt: skip


def _argv_routes(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-record-routes",
            "--onehop-root", str(ctx.inp("onehop_root")),
            "--albums", str(ctx.o(CATALOG)),
            "--release-format-policy", str(ctx.inp("release_format_policy")),
            "--studio-album-exclusions", str(ctx.inp("studio_album_exclusions")),
            "--masters-root", str(ctx.inp("masters_root")),
            *_optional(ctx, "artist_family_exclusions", "--artist-family-exclusions"),
            "--previous-routes-universe", str(ctx.p(ROUTES_UNIVERSE)),
            *_parameter_flags(ctx, "record_routes"),
            "--output-universe", str(ctx.o(ROUTES_UNIVERSE)),
            "--output-rounds", str(ctx.o(ROUTES_ROUNDS)),
        ]
    ]  # fmt: skip


def _frozen_rel(generation_id: str) -> str:
    return f"game/generations/{generation_id}/rounds.json"


def _argv_freeze(ctx: Ctx) -> list[list[str]]:
    argv = []
    for generation_id in live_generation_ids(ctx.manifest()):
        argv.append(
            [
                "freeze-connection-daily-manifest-generation",
                "--manifest", str(ctx.o(DAILY_MANIFEST)),
                "--generation-id", generation_id,
                "--source-rounds", str(ctx.p(GAME_ROUNDS)),
                "--frozen-output", str(ctx.o(_frozen_rel(generation_id))),
                "--rounds-url", "/data/" + _frozen_rel(generation_id),
                "--output", str(ctx.o(DAILY_MANIFEST)),
            ]
        )  # fmt: skip
    return argv


def _argv_connection(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-connection-rounds",
            "--onehop-root", str(ctx.inp("onehop_root")),
            "--albums", str(ctx.o(CATALOG)),
            *_optional(ctx, "artist_family_exclusions", "--artist-family-exclusions"),
            "--previous-connection-universe", str(ctx.p(GAME_UNIVERSE)),
            *_parameter_flags(ctx, "connection_rounds"),
            "--output-universe", str(ctx.o(GAME_UNIVERSE)),
            "--output-rounds", str(ctx.o(GAME_ROUNDS)),
        ]
    ]  # fmt: skip


def _argv_art(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-album-art-registry",
            "--catalog", str(ctx.o(CATALOG)),
            "--output", str(ctx.o(ART)),
            *_optional(ctx, "album_art_cache_dir", "--cache-dir"),
            "--generated-at", ctx.generated_at,
        ]
    ]  # fmt: skip


def _argv_evidence(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-evidence-release-registry",
            "--onehop-root", str(ctx.inp("onehop_root")),
            "--challenge", str(ctx.o(CHALLENGE)),
            "--routes-rounds", str(ctx.o(ROUTES_ROUNDS)),
            "--pathfinding-graph", str(ctx.o(GRAPH)),
            "--album-art", str(ctx.o(ART)),
            "--catalog", str(ctx.o(CATALOG)),
            "--output", str(ctx.o(EVIDENCE)),
            "--generated-at", ctx.generated_at,
        ]
    ]  # fmt: skip


def _argv_prominence(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-prominence",
            "--pathfinding-graph", str(ctx.o(GRAPH)),
            "--evidence-release-registry", str(ctx.o(EVIDENCE)),
            "--output", str(ctx.o(PROMINENCE)),
            "--generated-at", ctx.generated_at,
        ]
    ]  # fmt: skip


def _argv_contributors(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-contributor-index",
            "--challenge", str(ctx.o(CHALLENGE)),
            "--routes-universe", str(ctx.o(ROUTES_UNIVERSE)),
            "--routes-rounds", str(ctx.o(ROUTES_ROUNDS)),
            "--catalog", str(ctx.o(CATALOG)),
            "--evidence-release-registry", str(ctx.o(EVIDENCE)),
            "--output", str(ctx.o(CONTRIBUTORS)),
            "--generated-at", ctx.generated_at,
        ]
    ]  # fmt: skip


def _argv_search(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-search-index",
            "--catalog", str(ctx.o(CATALOG)),
            "--contributor-index", str(ctx.o(CONTRIBUTORS)),
            "--output", str(ctx.o(SEARCH)),
            "--generated-at", ctx.generated_at,
        ]
    ]  # fmt: skip


def _argv_hops(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-album-hop-distances",
            "--challenge", str(ctx.o(CHALLENGE)),
            "--routes-rounds", str(ctx.o(ROUTES_ROUNDS)),
            "--catalog", str(ctx.o(CATALOG)),
            "--contributor-index", str(ctx.o(CONTRIBUTORS)),
            "--output", str(ctx.o(HOP_DISTANCES)),
            "--generated-at", ctx.generated_at,
        ]
    ]  # fmt: skip


def _argv_migrate(ctx: Ctx) -> list[list[str]]:
    manifest = ctx.manifest()
    existing: list[str] = []
    for generation in manifest["generations"]:
        generation_id = generation["generation_id"]
        url = generation["rounds_url"]
        # The live generation is frozen by the preceding stage; name the path it
        # will have, so the plan shows the same arguments the run will use.
        rel = _frozen_rel(generation_id) if url == LIVE_ROUNDS_URL else url.removeprefix("/data/")
        existing += ["--existing-rounds", f"{generation_id}={ctx.o(rel)}"]
    return [
        [
            "migrate-connection-daily-manifest-generation",
            "--manifest", str(ctx.o(DAILY_MANIFEST)),
            "--new-rounds", str(ctx.o(GAME_ROUNDS)),
            "--cutover-date", cutover_date(ctx.spec).isoformat(),
            "--new-generation-id", str(ctx.spec["daily"]["new_generation_id"]),
            "--new-rounds-url", LIVE_ROUNDS_URL,
            "--days", str(ctx.spec["daily"]["days"]),
            "--generated-at", ctx.generated_at,
            *existing,
            "--output", str(ctx.o(DAILY_MANIFEST)),
        ]
    ]  # fmt: skip


def _argv_none(ctx: Ctx) -> list[list[str]]:
    return []


def _argv_theme_supply(ctx: Ctx) -> list[list[str]]:
    return [
        [
            "build-theme-candidates",
            "--seed-spec", str(ctx.inp("round_seed_spec")),
            "--dataset", str(ctx.inp("full_corpus_root")),
            "--masters-root", str(ctx.inp("masters_root")),
            "--release-format-policy", str(ctx.inp("release_format_policy")),
            # The policy is a one-hop index; masters outside that corpus need the
            # bounded classification of their releases from the full corpus.
            "--classify-pool-releases",
            "--studio-album-exclusions", str(ctx.inp("studio_album_exclusions")),
            "--already-published-catalog", str(ctx.p(CATALOG)),
            "--output", str(ctx.work / THEME_CANDIDATES),
            "--diagnostics-output", str(ctx.work / THEME_DIAGNOSTICS),
            "--merged-format-index-output", str(ctx.work / THEME_FORMAT_INDEX),
            "--quiet",
        ]
    ]  # fmt: skip


def _argv_rewiden(ctx: Ctx) -> list[list[str]]:
    onehop = ctx.inp("onehop_root")
    return [
        [
            "build-rewiden-seed",
            "--approved-pool", str(ctx.inp("approved_pool")),
            "--editorial-seed", str(ctx.inp("editorial_seed")),
            "--dataset", str(ctx.inp("full_corpus_root")),
            "--masters-root", str(ctx.inp("masters_root")),
            "--generated-at", ctx.generated_at,
            "--output", str(ctx.work / REWIDEN_SEED),
        ],
        [
            "expand-one-hop",
            "--seed", str(ctx.inp("private_seed")),
            "--additional-seed", str(ctx.work / REWIDEN_SEED),
            "--dataset", str(ctx.inp("full_corpus_root")),
            "--output-root", str(onehop.parent),
            "--overwrite",
            "--quiet",
        ],
    ]  # fmt: skip


def _freeze_guard(ctx: Ctx, planning: bool, *, freeze_pending: bool) -> list[str]:
    """The Round 1 incident as one condition: the connection-rounds stage would
    overwrite the file a daily-manifest generation still points at."""
    if freeze_pending:
        return []  # the freeze stage runs first and is checked on its own
    live = live_generation_ids(ctx.manifest())
    if not live:
        return []
    return [
        f"daily-manifest generation(s) {live} still point at the live rounds file "
        f"{LIVE_ROUNDS_URL}, which this stage overwrites -- every already-published date of "
        "that generation would stop resolving (Round 1: 90 dates). Run the "
        "'freeze-daily-generation' stage first (--from-stage freeze-daily-generation)"
    ]


def _pre_prepare(ctx: Ctx, planning: bool) -> list[str]:
    return []


def _pre_theme_supply(ctx: Ctx, planning: bool) -> list[str]:
    from networked_players_contracts.round_seed_spec import round_seed_spec_failures

    from .theme_supply_cli import ThemeSupplyError, require_private_ignored_output

    failures: list[str] = []
    try:
        for name in (THEME_CANDIDATES, THEME_DIAGNOSTICS, THEME_FORMAT_INDEX):
            require_private_ignored_output(ctx.work / name, command="theme-supply")
    except ThemeSupplyError as error:
        failures.append(f"{error} (paths.work_dir must be a git-ignored local/ path)")
    path = ctx.inputs["round_seed_spec"]
    if path is not None and path.is_file():
        try:
            seed_spec = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            return [*failures, f"round seed spec {path} is not JSON: {error}"]
        failures += [f"round seed spec: {f}" for f in round_seed_spec_failures(seed_spec)]
        if isinstance(seed_spec, dict):
            for key in ("round", "target_count"):
                if seed_spec.get(key) != ctx.spec[key]:
                    failures.append(
                        f"round seed spec {key} {seed_spec.get(key)!r} does not match the run "
                        f"spec's {ctx.spec[key]!r}"
                    )
    return failures


def _pre_rewiden(ctx: Ctx, planning: bool) -> list[str]:
    from .theme_supply_cli import ThemeSupplyError, require_private_ignored_output

    failures: list[str] = []
    try:
        require_private_ignored_output(ctx.work / REWIDEN_SEED, command="onehop-rewiden")
    except ThemeSupplyError as error:
        failures.append(f"{error} (paths.work_dir must be a git-ignored local/ path)")
    onehop = ctx.inputs["onehop_root"]
    corpus = ctx.inputs["full_corpus_root"]
    if corpus is not None and not (corpus / "manifest.json").is_file():
        failures.append(
            f"inputs.full_corpus_root {corpus} has no manifest.json (not a parsed snapshot); "
            "cannot check that onehop_root matches its snapshot date"
        )
    if onehop is not None and corpus is not None and (corpus / "manifest.json").is_file():
        try:
            date_ = str(json.loads((corpus / "manifest.json").read_text())["snapshot_date"])
        except (json.JSONDecodeError, KeyError) as error:
            return [*failures, f"full corpus manifest is unreadable: {error!r}"]
        if onehop.name != f"snapshot={date_}":
            failures.append(
                f"inputs.onehop_root must be named 'snapshot={date_}' (the full corpus's "
                f"snapshot): expand-one-hop writes <parent>/snapshot={date_}, so any other "
                "name would leave every later stage reading the stale corpus"
            )
        if onehop.resolve() == corpus.resolve():
            failures.append("inputs.onehop_root must not be the full corpus itself")
    return failures


def _pre_catalog(ctx: Ctx, planning: bool) -> list[str]:
    return [] if ctx.p(CATALOG).is_file() else [f"previous catalog {ctx.p(CATALOG)} is missing"]


def _pre_challenge(ctx: Ctx, planning: bool) -> list[str]:
    path = ctx.p(CHALLENGE)
    return (
        []
        if path.is_file()
        else [
            f"carry-forward challenge {path} is missing: without it contributor pages whose "
            "paths were documented earlier would 404 (--carry-forward-challenge is mandatory)"
        ]
    )


def _pre_routes(ctx: Ctx, planning: bool) -> list[str]:
    path = ctx.p(ROUTES_UNIVERSE)
    return (
        []
        if path.is_file()
        else [f"previous routes universe {path} is missing (--previous-routes-universe)"]
    )


def _pre_freeze(ctx: Ctx, planning: bool) -> list[str]:
    failures: list[str] = []
    live = live_generation_ids(ctx.manifest())
    if len(live) > 1:
        failures.append(f"generations {live} all point at the live rounds file; fix the manifest")
    if live and not ctx.p(GAME_ROUNDS).is_file():
        failures.append(
            f"{ctx.p(GAME_ROUNDS)} is missing: the freeze needs the exact pool generation "
            f"{live[0]!r} was scheduled against"
        )
    return failures


def _pre_connection(ctx: Ctx, planning: bool) -> list[str]:
    failures = _freeze_guard(ctx, planning, freeze_pending=_FREEZE_PENDING.get(id(ctx), False))
    path = ctx.p(GAME_UNIVERSE)
    if not path.is_file():
        failures.append(f"previous connection universe {path} is missing")
    return failures


def _pre_art(ctx: Ctx, planning: bool) -> list[str]:
    if ctx.art_builder is not None:
        return []
    failures = []
    if ctx.inputs["album_art_cache_dir"] is None:
        failures.append("inputs.album_art_cache_dir is null but the album-art stage needs it")
    if not os.environ.get("DISCOGS_TOKEN"):
        failures.append(
            "DISCOGS_TOKEN is not set (checked by presence only): the album-art stage calls "
            "the Discogs API; export it for this shell, never commit it"
        )
    return failures


def _pre_migrate(ctx: Ctx, planning: bool) -> list[str]:
    failures = calendar_failures(ctx.spec, today=ctx.today)
    manifest = ctx.manifest()
    failures += manifest_calendar_failures(manifest, ctx.spec)
    if not _FREEZE_PENDING.get(id(ctx), False):
        live = live_generation_ids(manifest)
        if live:
            failures.append(
                f"generation(s) {live} still point at {LIVE_ROUNDS_URL}, which the new "
                "generation claims; freeze first"
            )
    return failures


def _pre_format(ctx: Ctx, planning: bool) -> list[str]:
    if ctx.formatter is not None:
        return []
    reason = formatter_unavailable_reason()
    return [f"cannot run Prettier: {reason}. The format stage never skips"] if reason else []


# `plan` marks whether the freeze stage lies ahead in the selected range, so the
# connection-rounds guard can be evaluated as "satisfied once the freeze ran".
_FREEZE_PENDING: dict[int, bool] = {}


def _exec_argv_in_work_dir(ctx: Ctx, stage: Stage) -> None:
    ctx.work.mkdir(parents=True, exist_ok=True)
    for argv in stage.argv(ctx):
        _run_cli(ctx, stage.name, argv)


def _exec_prepare(ctx: Ctx, stage: Stage) -> None:
    """Take the daily-manifest baseline (and frozen generations) from P into O
    when O does not have them yet. A no-op when O already has them (a restart,
    or O is the tree the baseline was exported from)."""
    ctx.out.mkdir(parents=True, exist_ok=True)
    ctx.work.mkdir(parents=True, exist_ok=True)
    sources = [DAILY_MANIFEST]
    generations = ctx.p("game/generations")
    if generations.is_dir():
        sources += sorted(
            str(f.relative_to(ctx.prev)) for f in generations.rglob("*") if f.is_file()
        )
    for rel in sources:
        target = ctx.o(rel)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ctx.p(rel), target)


def _exec_freeze(ctx: Ctx, stage: Stage) -> None:
    argvs = stage.argv(ctx)
    if not argvs:
        ctx.log("  no generation points at the live rounds file; nothing to freeze")
        return
    for argv in argvs:
        _run_cli(ctx, stage.name, argv)


def _exec_art(ctx: Ctx, stage: Stage) -> None:
    if ctx.art_builder is not None:
        ctx.art_builder(ctx)
        return
    for argv in stage.argv(ctx):
        _run_cli(ctx, stage.name, argv)


def _exec_format(ctx: Ctx, stage: Stage) -> None:
    patterns = load_prettier_ignore()
    files = [
        ctx.o(rel)
        for rel in FORMATTABLE
        if ctx.o(rel).is_file() and not prettier_ignored(rel, patterns)
    ]
    formatter = ctx.formatter or default_formatter
    formatter(files)


def _exec_verify(ctx: Ctx, stage: Stage) -> None:
    ok, _ = verify_round(ctx)
    if not ok:
        raise RoundError(f"verification failed; see {ctx.work / 'report.md'} for the full list")


STAGES: tuple[Stage, ...] = (
    Stage("theme-supply", "build-theme-candidates",
          "SUPPLY: theme-seed candidates from the FULL corpus (private output); naming a "
          "theme approves nothing. Scoring, review and approval follow by hand",
          "full corpus, masters, policy, exclusions, previous catalog, round seed spec",
          ("<work>/theme-candidates.json", "<work>/theme-candidates-diagnostics.json",
           "<work>/theme-release-format-index.json"), _argv_theme_supply, _exec_argv_in_work_dir,
          _pre_theme_supply, True),
    Stage("prepare-output", "(internal)", "create O/W; take the daily-manifest baseline from P",
          "previous daily manifest + generations", (DAILY_MANIFEST,), _argv_prepare,
          _exec_prepare, _pre_prepare),
    Stage("onehop-rewiden", "build-rewiden-seed + expand-one-hop",
          "re-widen the one-hop corpus ONLY for approved albums (approved pool + committed "
          "editorial seed + private seed); replaces onehop_root by a rename-aside swap (old "
          "corpus restored on failure); workstation-only",
          "full corpus, approved pool, editorial seed, private seed",
          ("<work>/rewiden-seed.json", "onehop_root"), _argv_rewiden, _exec_argv_in_work_dir,
          _pre_rewiden, True),
    Stage("catalog", "build-public-album-catalog",
          "publish exactly the approved pool (two-way check); keep already-published albums",
          "one-hop, masters, policy, exclusions, approved pool, previous catalog",
          (CATALOG,), _argv_catalog, None, _pre_catalog),
    Stage("album-credit-membership", "build-album-credit-membership",
          "per-album performer membership", "one-hop, catalog", (MEMBERSHIP,), _argv_membership),
    Stage("pathfinding-graph", "build-pathfinding-graph", "performer graph with album anchors",
          "one-hop, catalog, membership", (GRAPH,), _argv_graph),
    Stage("challenge", "build-challenge-from-dump",
          "album-centred challenge; ALWAYS carries the previous challenge forward",
          "one-hop, masters, policy, exclusions, catalog, previous challenge",
          (CHALLENGE,), _argv_challenge, None, _pre_challenge),
    Stage("record-routes", "build-record-routes",
          "Record Routes pool; ALWAYS inherits the previous universe's targets",
          "one-hop, catalog, policy, exclusions, previous routes universe",
          (ROUTES_UNIVERSE, ROUTES_ROUNDS), _argv_routes, None, _pre_routes),
    Stage("freeze-daily-generation", "freeze-connection-daily-manifest-generation",
          "freeze the generation pointing at the live rounds file BEFORE the pool is regenerated",
          "daily manifest, previous live rounds file",
          (DAILY_MANIFEST, "game/generations/<id>/rounds.json"), _argv_freeze,
          _exec_freeze, _pre_freeze),
    Stage("connection-rounds", "build-connection-rounds",
          "Connection Guesser pool; ALWAYS inherits the previous universe's targets; "
          "refused while a generation still points at the live file",
          "one-hop, catalog, previous game universe", (GAME_UNIVERSE, GAME_ROUNDS),
          _argv_connection, None, _pre_connection),
    Stage("album-art-registry", "build-album-art-registry",
          "cover-art registry (Discogs API + private cache; operator command in a real run)",
          "catalog, API cache", (ART,), _argv_art, _exec_art, _pre_art),
    Stage("evidence-release-registry", "build-evidence-release-registry",
          "release registry covering every cited release id",
          "one-hop, challenge, routes rounds, graph, art, catalog", (EVIDENCE,), _argv_evidence),
    Stage("prominence", "build-prominence", "node ranking signals",
          "graph, evidence registry", (PROMINENCE,), _argv_prominence),
    Stage("contributor-index", "build-contributor-index", "derived /contributors/ pages",
          "challenge, routes, catalog, evidence registry", (CONTRIBUTORS,), _argv_contributors),
    Stage("search-index", "build-search-index", "site search index",
          "catalog, contributor index", (SEARCH,), _argv_search),
    Stage("album-hop-distances", "build-album-hop-distances", "hop labels for contributor pages",
          "challenge, routes rounds, catalog, contributor index", (HOP_DISTANCES,), _argv_hops),
    Stage("daily-manifest-migrate", "migrate-connection-daily-manifest-generation",
          "introduce the new generation at the cutover date; never cached or skipped",
          "daily manifest (frozen), new rounds", (DAILY_MANIFEST,), _argv_migrate,
          None, _pre_migrate),
    Stage("format", "(Prettier)", "format only what Prettier is meant to format "
          "(honours apps/web/.prettierignore)", "all written artifacts", FORMATTABLE,
          _argv_none, _exec_format, _pre_format),
    Stage("verify", "(validate-public-artifacts + continuity + daily manifest)",
          "validate, check continuity, write the round report", "O, P", ("<work>/report.md",),
          _argv_none, _exec_verify),
)  # fmt: skip

STAGE_NAMES = tuple(s.name for s in STAGES)


def select_stages(
    from_stage: str | None, to_stage: str | None, only_stage: str | None = None
) -> list[Stage]:
    """The stages a plan/run covers. The default range is the publish sequence; an
    opt-in stage (`theme-supply`, `onehop-rewiden`) is included only when named by
    `--from-stage`, `--to-stage` or `--only-stage`."""
    if only_stage is not None:
        if from_stage is not None or to_stage is not None:
            raise RoundError("--only-stage cannot be combined with --from-stage/--to-stage")
        if only_stage not in STAGE_NAMES:
            raise RoundError(f"--only-stage {only_stage!r} is not a stage")
        return [STAGES[STAGE_NAMES.index(only_stage)]]
    for label, name in (("--from-stage", from_stage), ("--to-stage", to_stage)):
        if name is not None and name not in STAGE_NAMES:
            raise RoundError(
                f"{label} {name!r} is not a stage; choose from: {', '.join(STAGE_NAMES)}"
            )
    start = STAGE_NAMES.index(from_stage) if from_stage else 0
    end = STAGE_NAMES.index(to_stage) if to_stage else len(STAGES) - 1
    if start > end:
        raise RoundError("--from-stage comes after --to-stage")
    if from_stage == "theme-supply" and to_stage != "theme-supply":
        # Supply is followed by scoring, owner review and approval, none of which the
        # runner performs; a range out of it would publish without that approval.
        raise RoundError(
            "--from-stage theme-supply would run on into the publish stages and skip "
            "scoring, owner review and approval. Run supply alone with --only-stage "
            "theme-supply (or --to-stage theme-supply); start publishing later with "
            "--from-stage onehop-rewiden or --from-stage prepare-output once the pool is approved"
        )
    named = {from_stage, to_stage}
    return [s for s in STAGES[start : end + 1] if not s.opt_in or s.name in named]


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def input_failures(ctx: Ctx, stages: Sequence[Stage] | None = None) -> list[str]:
    """Every input is explicit (checked structurally) and every stated path exists.
    Only existence is checked; private inputs are never opened here. Stage-scoped
    inputs (INPUT_STAGES) are enforced only when one of `stages` is selected."""
    failures: list[str] = []
    selected = {s.name for s in stages} if stages is not None else set()
    for name, (kind, required_by) in INPUT_SPECS.items():
        if name in INPUT_STAGES and not (INPUT_STAGES[name] & selected):
            continue
        path = ctx.inputs[name]
        if path is None:
            if required_by is not None:
                reason = ctx.spec["inputs"][name]["reason"]
                failures.append(f"inputs.{name} is null ({reason!r}) but {required_by} requires it")
            continue
        ok = path.is_dir() if kind == "dir" else path.is_file()
        if not ok:
            failures.append(f"inputs.{name}: {path} does not exist as a {kind}")
    return failures


def baseline_failures(ctx: Ctx) -> list[str]:
    failures: list[str] = []
    if ctx.prev.resolve() == ctx.out.resolve():
        failures.append(
            "paths.previous_artifacts_dir equals paths.output_dir: the baseline for carry-forward, "
            "inherited parameters and the continuity check would be overwritten by the first "
            "stage. Export the published artifacts to a separate directory first (e.g. "
            "`git archive HEAD apps/web/public/data | tar -x -C <scratch>`)"
        )
    if ctx.out.name != "data":
        failures.append(
            f"paths.output_dir {ctx.out} must be a directory named 'data' (the real target is "
            "apps/web/public/data): the freeze stage and validate-public-artifacts map the "
            "manifest's '/data/...' rounds URLs onto '<parent>/data/...'"
        )
    if not ctx.prev.is_dir():
        failures.append(f"paths.previous_artifacts_dir {ctx.prev} does not exist")
    for rel in (CATALOG, CHALLENGE, ROUTES_UNIVERSE, GAME_UNIVERSE, GAME_ROUNDS, CONTRIBUTORS,
                DAILY_MANIFEST):  # fmt: skip
        if ctx.prev.is_dir() and not ctx.p(rel).is_file():
            failures.append(f"previous artifacts are missing {rel}")
    if ctx.work.resolve() == ctx.out.resolve() or ctx.out.resolve() in ctx.work.resolve().parents:
        failures.append("paths.work_dir must not be inside the public output directory")
    return failures


def evaluate_preconditions(ctx: Ctx, stages: Sequence[Stage], *, planning: bool) -> list[str]:
    """All preconditions for the selected stages. Stage prechecks read the daily
    manifest and so need a baseline; they run only when the baseline is sound."""
    failures = input_failures(ctx, stages) + baseline_failures(ctx)
    try:
        _, parameter_failures = resolve_parameters(ctx)
        failures += parameter_failures
    except OSError as error:
        failures.append(f"cannot resolve build parameters: {error}")
    if failures and not ctx.p(DAILY_MANIFEST).is_file() and not ctx.o(DAILY_MANIFEST).is_file():
        return failures
    names = [s.name for s in stages]
    _FREEZE_PENDING[id(ctx)] = "freeze-daily-generation" in names
    try:
        for index, stage in enumerate(stages):
            if stage.precheck is None:
                continue
            # The guard on connection-rounds is "satisfied once freeze ran" only if
            # the freeze stage precedes it within the selected range.
            _FREEZE_PENDING[id(ctx)] = "freeze-daily-generation" in names[:index]
            failures += [f"[{stage.name}] {f}" for f in stage.precheck(ctx, planning)]
    except RoundError as error:
        failures.append(str(error))
    finally:
        _FREEZE_PENDING.pop(id(ctx), None)
    return failures


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def _stage_argv_text(ctx: Ctx, stage: Stage) -> list[str]:
    try:
        argvs = stage.argv(ctx)
    except RoundError as error:
        return [f"(arguments unavailable: {error})"]
    return [shlex.join(["networked-players-catalog", *argv]) for argv in argvs]


def plan_round(ctx: Ctx, stages: Sequence[Stage]) -> tuple[str, list[str]]:
    """Pure dry run: the plan text and the precondition failures. Writes nothing."""
    failures = evaluate_preconditions(ctx, stages, planning=True)
    lines = [
        f"Round {ctx.spec['round']} plan (target {ctx.spec['target_count']} albums; "
        f"themes: {', '.join(ctx.spec['themes']) or '(none)'})",
        f"  previous artifacts: {ctx.prev}",
        f"  output:             {ctx.out}",
        f"  daily cutover:      {cutover_date(ctx.spec)} (planned merge "
        f"{ctx.spec['planned_merge_date']} + {ctx.spec['daily']['cutover_lead_days']} days); "
        f"today {ctx.today}",
        "",
        "Stages:",
    ]
    for stage in stages:
        number = STAGE_NAMES.index(stage.name) + 1
        lines.append(f"  [{number}/{len(STAGES)}] {stage.name}: {stage.summary}")
        lines.append(f"      command: {stage.command}")
        lines.append(f"      reads:   {stage.reads}")
        lines.append(f"      writes:  {', '.join(stage.writes)}")
        for text in _stage_argv_text(ctx, stage):
            lines.append(f"      args:    {text}")
    try:
        resolved, _ = resolve_parameters(ctx)
    except OSError:
        resolved = {}
    lines += ["", "Build parameters (explicit / inherited / default):"]
    for builder, table in resolved.items():
        for name, entry in table.items():
            lines.append(f"  {builder}.{name} = {entry['value']!r} ({entry['source']})")
    lines += ["", "Preconditions:"]
    if failures:
        lines += [f"  FAIL {f}" for f in failures]
    else:
        lines.append("  all preconditions pass")
    return "\n".join(lines) + "\n", failures


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _run_cli(ctx: Ctx, stage_name: str, argv: list[str]) -> Any:
    from .cli import main

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = main(argv)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 2
    if code != 0:
        raise StageFailure(stage_name, f"`{argv[0]}` exited {code}")
    text = buffer.getvalue()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        summary = {k: v for k, v in parsed.items() if isinstance(v, str | int | float | bool)}
        if isinstance(parsed.get("build_parameters"), dict):
            summary["build_parameters"] = parsed["build_parameters"]
        ctx.results.setdefault(stage_name, []).append(summary)
    return parsed


def _results_path(ctx: Ctx) -> Path:
    return ctx.work / "stage-results.json"


def _load_results(ctx: Ctx) -> None:
    path = _results_path(ctx)
    if path.is_file():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            ctx.results.update(json.loads(path.read_text()))


def _save_results(ctx: Ctx) -> None:
    ctx.work.mkdir(parents=True, exist_ok=True)
    _results_path(ctx).write_text(json.dumps(ctx.results, indent=2, sort_keys=True) + "\n")


def run_round(
    ctx: Ctx,
    *,
    from_stage: str | None = None,
    to_stage: str | None = None,
    only_stage: str | None = None,
) -> int:
    stages = select_stages(from_stage, to_stage, only_stage)
    failures = evaluate_preconditions(ctx, stages, planning=False)
    if failures:
        ctx.log("round run refused; preconditions failed:")
        for failure in failures:
            ctx.log(f"  - {failure}")
        return 2
    ctx.work.mkdir(parents=True, exist_ok=True)
    _load_results(ctx)
    total = len(STAGES)
    for stage in stages:
        number = STAGE_NAMES.index(stage.name) + 1
        ctx.log(f"[{number}/{total}] {stage.name}: start")
        try:
            # Re-check immediately before executing: an earlier stage in this
            # very run may have changed the state a guard reads.
            live_failures = [] if stage.precheck is None else stage.precheck(ctx, False)
            if live_failures:
                raise StageFailure(stage.name, "; ".join(live_failures))
            if stage.execute is not None:
                stage.execute(ctx, stage)
            else:
                for argv in stage.argv(ctx):
                    _run_cli(ctx, stage.name, argv)
            _save_results(ctx)
        except (RoundError, ValueError, KeyError, OSError, RuntimeError) as error:
            message = (
                str(error)
                if isinstance(error, StageFailure)
                else f"{type(error).__name__}: {error}"
            )
            ctx.log(f"[{number}/{total}] {stage.name}: FAILED")
            ctx.log(
                f"round run stopped at stage {stage.name!r}: {message}\n"
                f"Fix it, then restart with --from-stage {stage.name}"
            )
            return 1
        ctx.log(f"[{number}/{total}] {stage.name}: finish")
    return 0


# ---------------------------------------------------------------------------
# verify and the report
# ---------------------------------------------------------------------------


def artifact_versions(root: Path) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name, rel in ARTIFACT_PATHS.items():
        path = root / rel
        if not path.is_file():
            versions[name] = None
            continue
        try:
            versions[name] = artifact_content_version(name, json.loads(path.read_text()))
        except json.JSONDecodeError:
            versions[name] = None
    return versions


def _capture_cli(argv: list[str]) -> tuple[int, Any]:
    from .cli import main

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
            code = main(argv)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 2
    except Exception as error:  # a builder/validator refusing is a verification result
        return 1, {"error": f"{type(error).__name__}: {error}"}
    try:
        return code, json.loads(buffer.getvalue())
    except json.JSONDecodeError:
        return code, None


def _validate_argv(ctx: Ctx) -> list[str]:
    return [
        "validate-public-artifacts",
        "--catalog", str(ctx.o(CATALOG)),
        "--album-art", str(ctx.o(ART)),
        "--connection-universe", str(ctx.o(GAME_UNIVERSE)),
        "--connection-rounds", str(ctx.o(GAME_ROUNDS)),
        "--daily-manifest", str(ctx.o(DAILY_MANIFEST)),
        "--routes-universe", str(ctx.o(ROUTES_UNIVERSE)),
        "--routes-rounds", str(ctx.o(ROUTES_ROUNDS)),
        "--challenge", str(ctx.o(CHALLENGE)),
        "--contributor-index", str(ctx.o(CONTRIBUTORS)),
        "--album-hop-distances", str(ctx.o(HOP_DISTANCES)),
        "--pathfinding-graph", str(ctx.o(GRAPH)),
        "--prominence", str(ctx.o(PROMINENCE)),
        "--album-credit-membership", str(ctx.o(MEMBERSHIP)),
        "--evidence-release-registry", str(ctx.o(EVIDENCE)),
        "--search-index", str(ctx.o(SEARCH)),
        "--approved-pool", str(ctx.inp("approved_pool")),
        "--daily-manifest-pin", str(ctx.inp("daily_manifest_pin")),
        "--payload-budgets", str(ctx.inp("payload_budgets")),
        "--data-root", str(ctx.out),
    ]  # fmt: skip


def verify_round(ctx: Ctx) -> tuple[bool, dict[str, Any]]:
    """Validate the output directory and write the Markdown round report."""
    problems: list[str] = []
    missing = [rel for rel in (*ARTIFACT_PATHS.values(), GAME_ROUNDS, ROUTES_ROUNDS, DAILY_MANIFEST)
               if not ctx.o(rel).is_file()]  # fmt: skip
    if missing:
        problems.append(f"output directory is missing: {', '.join(missing)}")
        report: dict[str, Any] = {"problems": problems}
        _write_report(ctx, report, ok=False)
        return False, report

    code, validation = _capture_cli(_validate_argv(ctx))
    validation = validation or {"ok": False, "failures": {"cli": [f"exit {code}"]}, "lineage": {}}
    if "error" in validation:
        validation = {"ok": False, "failures": {"cli": [validation["error"]]}, "lineage": {}}
    if not validation.get("ok"):
        for group, items in (validation.get("failures") or {}).items():
            problems += [f"validate-public-artifacts [{group}]: {item}" for item in items]
        if not validation.get("failures"):
            problems.append(f"validate-public-artifacts exited {code}")
    lineage = validation.get("lineage") or {}
    if lineage.get("undeclared_inputs"):
        problems.append(f"lineage.undeclared_inputs is not empty: {lineage['undeclared_inputs']}")
    if lineage.get("partially_declared_inputs"):
        partial = lineage["partially_declared_inputs"]
        problems.append(f"lineage.partially_declared_inputs is not empty: {partial}")

    hops_code, hops_result = _capture_cli(
        [
            "check-challenge-hops-in-graph",
            "--challenge", str(ctx.o(CHALLENGE)),
            "--pathfinding-graph", str(ctx.o(GRAPH)),
        ]
    )  # fmt: skip
    if hops_code != 0:
        listed = (hops_result or {}).get("failures") or [f"exit {hops_code}"]
        problems += [f"challenge hop not in graph: {item}" for item in listed]

    continuity_code, continuity = _capture_cli(
        [
            "check-contributor-continuity",
            "--previous-challenge", str(ctx.p(CHALLENGE)),
            "--current-challenge", str(ctx.o(CHALLENGE)),
            "--previous-contributor-index", str(ctx.p(CONTRIBUTORS)),
            "--current-contributor-index", str(ctx.o(CONTRIBUTORS)),
        ]
    )  # fmt: skip
    if continuity_code != 0 or continuity is None:
        lost = ((continuity or {}).get("path_endpoints") or {}).get("lost")
        problems.append(
            f"contributor continuity failed: previously documented endpoints lost: {lost}"
        )

    manifest = json.loads(ctx.o(DAILY_MANIFEST).read_text())
    previous_manifest = json.loads(ctx.p(DAILY_MANIFEST).read_text())
    problems += daily_manifest_continuity_failures(previous_manifest, manifest, today=ctx.today)
    rounds_args: list[str] = []
    for generation in manifest.get("generations", []):
        rel = generation["rounds_url"].removeprefix("/data/")
        rounds_args += ["--rounds", f"{generation['generation_id']}={ctx.o(rel)}"]
    manifest_code, manifest_result = _capture_cli(
        [
            "validate-connection-daily-manifest-v2",
            "--manifest",
            str(ctx.o(DAILY_MANIFEST)),
            *rounds_args,
        ]
    )
    if manifest_code != 0:
        detail = (manifest_result or {}).get("error", "")
        problems.append(
            f"daily manifest: not every scheduled date resolves against its generation {detail}"
        )

    report = {
        "problems": problems,
        "validation": validation,
        "continuity": continuity,
        "lineage": lineage,
        "versions_before": artifact_versions(ctx.prev),
        "versions_after": artifact_versions(ctx.o("")),
    }
    ok = not problems
    _write_report(ctx, report, ok=ok)
    return ok, report


def _album_labels(catalog_path: Path) -> dict[int, str]:
    if not catalog_path.is_file():
        return {}
    albums = json.loads(catalog_path.read_text()).get("albums", [])
    return {
        int(a["master_id"]): f"{a.get('artist')} - {a.get('title')}"
        for a in albums
        if a.get("master_id") is not None
    }


def _write_report(ctx: Ctx, report: dict[str, Any], *, ok: bool) -> None:
    _load_results(ctx)
    spec = ctx.spec
    before = _album_labels(ctx.p(CATALOG))
    after = _album_labels(ctx.o(CATALOG))
    lines = [
        f"# Round {spec['round']} report",
        "",
        f"Verification: **{'PASS' if ok else 'FAIL'}**. "
        f"Themes: {', '.join(spec['themes']) or '(none)'}. "
        f"Target: {spec['target_count']} albums. generated_at: {spec['generated_at']}.",
        "",
        "## Problems",
        "",
    ]
    lines += [f"- {p}" for p in report.get("problems", [])] or ["None."]
    lines += ["", "## Albums", "", f"{len(before)} before, {len(after)} after."]
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    lines += [f"- added: master {m} ({after[m]})" for m in added] or ["- added: none"]
    lines += [f"- REMOVED: master {m} ({before[m]})" for m in removed]
    lines += [
        "",
        "## Artifact content versions",
        "",
        "| artifact | before | after |",
        "| --- | --- | --- |",
    ]
    vb = report.get("versions_before", {})
    va = report.get("versions_after", {})
    for name in ARTIFACT_PATHS:
        b, a = vb.get(name), va.get(name)
        lines.append(
            f"| {name} | {b or '(none)'} | {a or '(none)'}{'' if a != b else ' (unchanged)'} |"
        )
    lineage = report.get("lineage") or {}
    lines += [
        "",
        "## Declared lineage",
        "",
        f"- undeclared_inputs: {lineage.get('undeclared_inputs', 'unknown')}",
        f"- partially_declared_inputs: {lineage.get('partially_declared_inputs', 'unknown')}",
        "",
        "## Contributor pages",
        "",
    ]
    continuity = report.get("continuity") or {}
    index = continuity.get("contributor_index") or {}
    endpoints = continuity.get("path_endpoints") or {}
    if index:
        lines += [
            f"- index: {index.get('previous')} -> {index.get('current')} "
            f"(added {index.get('added')}, removed {index.get('removed')})",
            f"- documented path endpoints lost: {len(endpoints.get('lost', []))} "
            f"of {endpoints.get('previous')}",
        ]
    else:
        lines.append("- not computed")
    lines += ["", "## Daily manifest", ""]
    if ctx.o(DAILY_MANIFEST).is_file():
        manifest = json.loads(ctx.o(DAILY_MANIFEST).read_text())
        lines += [
            f"- generations: {[g['generation_id'] for g in manifest.get('generations', [])]}",
            f"- newest generation cutover: {newest_generation_cutover(manifest)}",
            f"- scheduled dates: {len(manifest.get('schedule', []))}",
        ]
    lines += ["", "## Builder parameters (source: explicit / inherited / default)", ""]
    any_parameters = False
    for stage_name, entries in sorted(ctx.results.items()):
        for entry in entries:
            parameters = entry.get("build_parameters")
            if isinstance(parameters, dict):
                any_parameters = True
                for name, item in sorted(parameters.items()):
                    source = {"cli": "explicit"}.get(item.get("source"), item.get("source"))
                    lines.append(f"- {stage_name}.{name} = {item.get('value')!r} ({source})")
    if not any_parameters:
        lines.append("Not recorded (no stage results in the work directory).")
    lines += [
        "",
        "Other builders take only explicit flags (spec inputs, `generated_at`, "
        "`target_count`, `expansion_round`).",
        "",
        "No timing or memory figures are recorded here (ADR 0018).",
    ]
    ctx.work.mkdir(parents=True, exist_ok=True)
    (ctx.work / "report.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register_round_parser(subparsers: Any) -> None:
    round_parser = subparsers.add_parser(
        "round",
        help=(
            "operator-run round runner (ADR 0072 section 3): plan / run / verify the ordered "
            "rebuild of every public artifact for a catalog round. Never run in CI."
        ),
    )
    actions = round_parser.add_subparsers(dest="round_action", required=True)
    for name, help_text in (
        ("plan", "dry run: validate the spec, resolve every argument, evaluate preconditions"),
        ("run", "execute the stages in order; restartable with --from-stage"),
        ("verify", "validate the output directory and write the round report"),
    ):
        sub = actions.add_parser(name, help=help_text)
        sub.add_argument("--spec", type=Path, required=True)
        sub.add_argument("--today", help="explicit ISO date (default: today, UTC)")
        if name in ("plan", "run"):
            sub.add_argument("--from-stage", choices=STAGE_NAMES)
            sub.add_argument("--to-stage", choices=STAGE_NAMES)
            sub.add_argument(
                "--only-stage",
                choices=STAGE_NAMES,
                help="run exactly one stage (the way to run an opt-in stage alone)",
            )
    cutover = actions.add_parser(
        "check-cutover",
        help=(
            "CI-safe pure check for a round PR: the daily manifest's newest generation must "
            "start strictly after --today"
        ),
    )
    cutover.add_argument("--manifest", type=Path, required=True)
    cutover.add_argument("--today", required=True, help="explicit ISO date")


def round_main(
    args: argparse.Namespace,
    *,
    formatter: Formatter | None = None,
    art_builder: ArtBuilder | None = None,
    stdout: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    if args.round_action == "check-cutover":
        failures = cutover_still_future_failures(
            json.loads(args.manifest.read_text()), today=args.today
        )
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        print(json.dumps({"ok": not failures, "failures": failures}, indent=2), file=out)
        return 1 if failures else 0
    today = date.fromisoformat(args.today) if args.today else datetime.now(UTC).date()
    try:
        spec = load_spec(args.spec)
        ctx = build_ctx(spec, today=today, formatter=formatter, art_builder=art_builder)
        if args.round_action == "plan":
            text, failures = plan_round(
                ctx, select_stages(args.from_stage, args.to_stage, args.only_stage)
            )
            out.write(text)
            return 1 if failures else 0
        if args.round_action == "run":
            return run_round(
                ctx, from_stage=args.from_stage, to_stage=args.to_stage, only_stage=args.only_stage
            )
        # verify
        failures = input_failures(ctx, ()) + baseline_failures(ctx)
        if failures:
            for failure in failures:
                print(f"FAIL {failure}", file=sys.stderr)
            return 2
        ok, report = verify_round(ctx)
        for problem in report.get("problems", []):
            print(f"FAIL {problem}", file=sys.stderr)
        print(f"report: {ctx.work / 'report.md'}", file=out)
        return 0 if ok else 1
    except RoundError as error:
        print(f"round: {error}", file=sys.stderr)
        return 2
