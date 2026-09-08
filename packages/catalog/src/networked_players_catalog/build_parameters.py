"""Resolve a builder's parameters from CLI arguments, the previously published
artifact's own `build_parameters` block, and hard-coded defaults -- in that
order of precedence.

Why this exists (graph-expansion plan Y3, follow-up to PR #248): Round 1 hit
silent-default drift three times. The worst was `build-record-routes` running
with `--two-hop-target`'s CLI default of 100 when the published artifact held
200, which halved the two-hop pool and quietly dropped 94 routes-only
contributor pages -- diagnosed a round later. PR #248 made each builder
*stamp* the parameters it ran with. This module is the other half: reading
that block back, so a rebuild reproduces the previous build instead of
silently inheriting a changed default.

Two design rules earn their own note, because both are easy to get wrong:

1. **Membership, never truthiness.** `--max-frontier-expansion 0` is a real,
   deliberate operator choice that the challenge builder stamps as `null`
   (and `contracts/challenge.py` explicitly permits null). `expansion_round`
   is legitimately `0`. So "absent from the previous block" must be tested
   with `key in previous`, never `previous.get(key)` -- otherwise an
   inherited `null`/`0` is indistinguishable from "not recorded" and any
   `a or b or DEFAULT` chain silently re-enables a bound the operator turned
   off. The CLI's own "not supplied" sentinel is `None`, which lives at a
   different *level* of the chain, so the two never collide.

2. **Missing is not malformed.** A previous artifact with no block at all is
   the normal case today (no committed artifact carried one before this
   landed) and must degrade quietly to defaults. A block that is present but
   the wrong shape is a real problem: silently ignoring it would reintroduce
   exactly the drift being fixed, so it raises.

This module is deliberately pure -- no DuckDB, no filesystem, no argparse --
so the precedence rules are testable on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Command-scoped so nobody is tempted to share them. `build-rounds`
# (400/100) and `build-connection-rounds` (300/200) use the same flag NAMES
# with different values, and homogenizing them would be a silent behaviour
# change to two commands this work never intended to touch.
RECORD_ROUTES_DEFAULT_BUILD_PARAMETERS: dict[str, Any] = {
    "one_hop_target": 150,
    "two_hop_target": 100,
    "max_endpoint_share": 0.15,
    "max_bridge_share": 0.2,
}

CHALLENGE_DEFAULT_BUILD_PARAMETERS: dict[str, Any] = {
    "max_hops": 4,
    "max_frontier_expansion": 300,
}


class BuildParametersError(ValueError):
    """A previous artifact carries a `build_parameters` block that is present
    but unusable. Deliberately not the same as "absent" -- see the module
    docstring."""


@dataclass(frozen=True, slots=True)
class Resolution:
    """One resolved parameter and where its value came from."""

    value: Any
    source: str  # "cli" | "inherited" | "default"


def read_previous_build_parameters(
    payload: Any, *, flag: str, at: str = "top_level"
) -> dict[str, Any] | None:
    """Extract the `build_parameters` block from an already-parsed previous
    artifact, or `None` when the artifact simply doesn't carry one.

    `at` selects where the block lives, which differs by artifact and is not
    a detail this module should guess: `"provenance"` for the Record Routes
    universe and `challenge.v3.json`, `"top_level"` for the public album
    catalog (see PR #248's three stamping sites).

    Raises `BuildParametersError` -- naming `flag`, so the operator knows
    which file to look at -- when the artifact or the block is present but
    the wrong shape.
    """
    if not isinstance(payload, dict):
        raise BuildParametersError(f"{flag} does not contain a JSON object")

    if at == "provenance":
        provenance = payload.get("provenance")
        if provenance is None:
            return None
        if not isinstance(provenance, dict):
            raise BuildParametersError(f"{flag}: provenance is not an object")
        container: dict[str, Any] = provenance
    elif at == "top_level":
        container = payload
    else:  # pragma: no cover - programmer error, not operator input
        raise ValueError(f"unknown build_parameters location {at!r}")

    if "build_parameters" not in container:
        return None
    block = container["build_parameters"]
    if not isinstance(block, dict):
        raise BuildParametersError(
            f"{flag}: build_parameters is present but is not an object "
            f"(got {type(block).__name__}) -- refusing to guess what this build ran with"
        )
    return block


def resolve_build_parameters(
    *,
    supplied: dict[str, Any],
    previous: dict[str, Any] | None,
    defaults: dict[str, Any],
) -> dict[str, Resolution]:
    """Resolve each parameter in `defaults` by precedence: an explicit CLI
    value wins, then the previous artifact's recorded value, then the
    hard-coded default.

    `supplied` maps parameter name -> the CLI value, where `None` means "the
    flag was not passed" (the repo's only established sentinel idiom, used by
    `--max-paths` already). `previous` is the block from
    `read_previous_build_parameters`, or `None`.

    Inheritance is decided by MEMBERSHIP in `previous`, never by truthiness,
    so a recorded `null` or `0` inherits correctly. See the module docstring.
    """
    previous_block = previous or {}
    resolved: dict[str, Resolution] = {}
    for name, fallback in defaults.items():
        cli_value = supplied.get(name)
        if cli_value is not None:
            resolved[name] = Resolution(cli_value, "cli")
        elif name in previous_block:
            resolved[name] = Resolution(previous_block[name], "inherited")
        else:
            resolved[name] = Resolution(fallback, "default")
    return resolved


def values(resolutions: dict[str, Resolution]) -> dict[str, Any]:
    """Just the resolved values, for splatting into a builder call."""
    return {name: resolution.value for name, resolution in resolutions.items()}


def summary(resolutions: dict[str, Resolution]) -> dict[str, dict[str, Any]]:
    """The machine-readable form for a command's stdout JSON summary, so a
    round log can record what a build actually ran with."""
    return {
        name: {"value": resolution.value, "source": resolution.source}
        for name, resolution in resolutions.items()
    }


def format_build_parameters_report(
    resolutions: dict[str, Resolution],
    *,
    command: str,
    previous_label: str | None,
) -> str:
    """A human-readable stderr report.

    `previous_label` is a description of where inherited values came from, or
    `None` when no previous artifact was supplied. **The no-previous-artifact
    case is reported, not skipped** -- it is the loudest branch, because
    piggybacking inheritance onto an optional flag means forgetting that flag
    silently returns you to exactly the failure this feature exists to
    prevent, which is how Round 1 went wrong in the first place.
    """
    lines = [f"{command}: build parameters"]
    if previous_label is None:
        lines.append(
            "  no previous artifact given -- nothing inherited; every value below is a "
            "CLI argument or a hard-coded default"
        )
    else:
        lines.append(f"  comparing against {previous_label}")
    width = max((len(name) for name in resolutions), default=0)
    for name, resolution in sorted(resolutions.items()):
        lines.append(f"  {name.ljust(width)}  {resolution.value!r} ({resolution.source})")
    return "\n".join(lines)
