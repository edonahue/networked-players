"""Artifact-registration completeness (post-Phase-4 cleanup audit F19/F20):
proves every real public artifact (`networked_players_contracts.
public_artifacts.PUBLIC_ARTIFACT_GROUPS`) that has a per-artifact Pi
check has a matching entry in both real registries a Pi-fleet check
actually goes through -- `workloads.py`'s `_artifact_validators()` (what
`packages/platform`'s `artifact.validate` workload dispatches to) and
`scripts/submit_artifact_check.py`'s `_DEFAULT_ARTIFACTS` (what supplies a
real default artifact path when no `--artifact` override is given).

This is exactly the class of gap the real rollback drill (ADR 0058 Slice
11) hit: five independent registries (`PUBLIC_ARTIFACT_GROUPS`,
`_artifact_validators()`, `_DEFAULT_ARTIFACTS`, the Makefile's
`*-check-distributed` targets, `docs/OPERATOR_SETUP.md`'s reference table)
can each be updated by hand when a new artifact type ships, and nothing
before this test ever caught one being missed. The Makefile targets
themselves aren't asserted here -- parsing a Makefile for this is
brittle relative to the real value; that one is a manual reviewer-checklist
item instead (see the PR that added this test).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from networked_players_contracts.public_artifacts import PUBLIC_ARTIFACT_GROUPS
from networked_players_platform.workloads import _artifact_validators

REPO_ROOT = Path(__file__).resolve().parents[3]

# Maps each PUBLIC_ARTIFACT_GROUPS name (networked_players_contracts.
# public_artifacts) to the corresponding `artifact.validate` name used by
# `_artifact_validators()`/`_DEFAULT_ARTIFACTS` -- deliberately an explicit
# table, not a naming-convention guess, since the two sides don't share one
# spelling convention (e.g. "connection_guesser" here is "connection-rounds"
# there). "challenge" and "album_hop_distances" are the real public artifact
# groups with NO per-artifact Pi check by design (docs/OPERATOR_SETUP.md's
# reference table: validated only via `validate-public-artifacts`/
# `make check`) -- "challenge" since it's a one-shot static artifact with no
# independent `artifact_version` to re-verify in isolation, and
# "album_hop_distances" (ADR 0048 addendum) since it's a small, cheap,
# purely-derived companion to `contributor_index` with no independent
# operational need yet for a distributed re-check separate from that
# artifact's own -- deliberately absent from this map, not a gap this test
# should flag.
_VALIDATOR_NAME_BY_ARTIFACT_GROUP = {
    "catalog": "catalog",
    "album_art_registry": "album-art",
    "connection_guesser": "connection-rounds",
    "connection_daily_manifest": "daily-manifest",
    "record_routes": "record-routes",
    "contributor_index": "contributor-index",
    "pathfinding_graph_v2": "pathfinding-graph",
    "album_credit_membership": "album-credit-membership",
    "evidence_release_registry": "evidence-release-registry",
}
_ARTIFACT_GROUPS_WITHOUT_A_PI_CHECK = frozenset({"challenge", "album_hop_distances"})


def test_every_public_artifact_group_is_accounted_for() -> None:
    """Every real name in PUBLIC_ARTIFACT_GROUPS is either mapped to a
    validator name above or explicitly named as intentionally
    unchecked -- catches a new artifact type shipping without anyone
    updating this table, the same class of miss the rollback drill hit."""
    accounted_for = set(_VALIDATOR_NAME_BY_ARTIFACT_GROUP) | _ARTIFACT_GROUPS_WITHOUT_A_PI_CHECK
    assert set(PUBLIC_ARTIFACT_GROUPS) == accounted_for


def test_every_pi_checked_artifact_group_has_a_workload_validator() -> None:
    validators = _artifact_validators()
    missing = sorted(
        name for name in _VALIDATOR_NAME_BY_ARTIFACT_GROUP.values() if name not in validators
    )
    assert missing == []


def _load_submit_artifact_check() -> ModuleType:
    """`scripts/submit_artifact_check.py` is a loose script, not part of
    any installed package -- it imports its sibling `_platform_client`
    module by bare name, so `scripts/` must be on `sys.path` for that
    import to resolve. Loaded via `importlib.util` (not a bare `import`)
    since `scripts` isn't itself a package with an `__init__.py`."""
    scripts_dir = REPO_ROOT / "scripts"
    scripts_dir_str = str(scripts_dir)
    if scripts_dir_str not in sys.path:
        sys.path.insert(0, scripts_dir_str)
    spec = importlib.util.spec_from_file_location(
        "submit_artifact_check", scripts_dir / "submit_artifact_check.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_pi_checked_artifact_group_has_a_submit_check_default() -> None:
    default_artifacts = _load_submit_artifact_check()._DEFAULT_ARTIFACTS
    missing = sorted(
        name for name in _VALIDATOR_NAME_BY_ARTIFACT_GROUP.values() if name not in default_artifacts
    )
    assert missing == []
