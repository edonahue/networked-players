"""Validates the whole real-artifact publication set as one unit.

Every real public artifact already has its own dependency-free validator in
this package (`catalog.py`, `album_art.py`, `connection_rounds.py`,
`connection_daily_manifest.py`, `record_routes.py`, `challenge.py`). Before
this module, nothing ever called them all together against the actual
committed files under `apps/web/public/data/**` -- CI validated the
synthetic test fixture (`apps/web/scripts/build-rounds.mjs --check`) and
every dependency-free validator's own unit tests, but never the real,
currently-published JSON itself. A defect in a real committed artifact
(missing field, stale version, dangling reference) could reach `main` and
stay there undetected.

This module is pure orchestration -- no file I/O, no hardcoded paths (those
live in the CLI adapter, `networked_players_catalog.cli`'s
`validate-public-artifacts` command, mirroring every check-job adapter's
"logic here, I/O there" split). Callers pass in already-loaded JSON.

Scoped to files actually under `apps/web/public/data/**` -- i.e. things a
browser can fetch. `docs/data/studio-album-catalog-inclusion-audit-v1.json`
is committed but not a public web artifact, so it is deliberately not one
of these groups; it has its own `validate-album-catalog-audit` CLI command
and `make check` step instead, kept honestly separate rather than folded in
under a "public artifacts" name that would then be inaccurate.
"""

from __future__ import annotations

from typing import Any

from .album_art import album_art_failures
from .album_credit_membership import album_credit_membership_failures
from .album_hop_distances import album_hop_distances_failures
from .catalog import public_album_catalog_failures
from .challenge import challenge_failures
from .connection_daily_manifest import (
    CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2,
    connection_daily_manifest_failures,
    connection_daily_manifest_v2_failures,
)
from .connection_rounds import connection_rounds_failures
from .contributor_index import contributor_index_failures
from .evidence_release_registry import evidence_release_registry_failures
from .pathfinding_graph import pathfinding_graph_failures
from .record_routes import record_routes_failures

# Keys match the checked-in game/routes namespaces, not `packages/contracts`
# module names, so a caller reading a failure report never has to guess
# which real files a given key corresponds to.
PUBLIC_ARTIFACT_GROUPS = (
    "catalog",
    "album_art_registry",
    "connection_guesser",
    "connection_daily_manifest",
    "record_routes",
    "challenge",
    "contributor_index",
    "album_hop_distances",
    "pathfinding_graph",
    "pathfinding_graph_v4",
    "album_credit_membership",
    "evidence_release_registry",
)


def public_artifacts_failures(
    *,
    catalog: Any,
    album_art: Any,
    connection_universe: Any,
    connection_rounds: Any,
    daily_manifest: Any,
    daily_manifest_rounds_by_generation: Any = None,
    routes_universe: Any,
    routes_rounds: Any,
    challenge: Any,
    contributor_index: Any,
    album_hop_distances: Any,
    pathfinding_graph: Any,
    pathfinding_graph_v4: Any,
    album_credit_membership: Any,
    evidence_release_registry: Any,
) -> dict[str, list[str]]:
    """Every contract failure across the whole real-artifact publication set,
    grouped by artifact. Every key in `PUBLIC_ARTIFACT_GROUPS` is always
    present, with an empty list when that artifact is clean -- callers can
    report "N/N clean" without special-casing an absent key.

    `challenge` is the single live artifact of its kind: `challenge.v3.json`,
    performer-gated (ADR 0068). Its v2 predecessor went through the same
    dual-live-then-retire sequence ADR 0058 established for `graph.v1.json`
    -- published alongside the old file, validated here from day one so a
    defect was caught by `make check` rather than by a consumer, cut over
    once, then deleted as an explicit separate step.

    `pathfinding_graph` (`pathfinding/graph.v3.json`) and
    `pathfinding_graph_v4` (`pathfinding/graph.v4.json`, ADR 0071's
    role-dictionary encoding) are DUAL-LIVE as of graph-expansion Phase 1:
    v3 remains the only artifact any real consumer fetches; v4 is published
    and validated here from day one, the same reason challenge's v2/v3
    transition validated its new file before any consumer cut over, so a
    defect is caught by `make check` rather than discovered mid-migration.
    Once every consumer (Connect, Explore, the private research workbench,
    the fleet artifact-check default) has cut over to v4, `pathfinding_graph`
    will be repointed at the v4 file and `pathfinding_graph_v4` retired as
    its own explicit step -- the same collapse-to-one-group precedent v1's
    retirement set. Both keys use the same schema-version-aware
    `pathfinding_graph_failures`, which continues to accept every schema
    version it has always validated; only the published artifact SET
    changes over time, never the validator."""
    return {
        "catalog": public_album_catalog_failures(catalog),
        "album_art_registry": album_art_failures(album_art, catalog),
        "connection_guesser": connection_rounds_failures(connection_universe, connection_rounds),
        "connection_daily_manifest": _daily_manifest_failures(
            daily_manifest, connection_rounds, daily_manifest_rounds_by_generation
        ),
        "record_routes": record_routes_failures(routes_universe, routes_rounds),
        "challenge": challenge_failures(challenge, catalog),
        "contributor_index": contributor_index_failures(contributor_index, catalog),
        "album_hop_distances": album_hop_distances_failures(
            album_hop_distances, catalog, contributor_index
        ),
        "pathfinding_graph": pathfinding_graph_failures(pathfinding_graph, catalog),
        "pathfinding_graph_v4": pathfinding_graph_failures(pathfinding_graph_v4, catalog),
        "album_credit_membership": album_credit_membership_failures(
            album_credit_membership, catalog
        ),
        "evidence_release_registry": evidence_release_registry_failures(
            evidence_release_registry, catalog
        ),
    }


def _daily_manifest_failures(
    daily_manifest: Any,
    connection_rounds: Any,
    rounds_by_generation: Any,
) -> list[str]:
    """Dispatch on the manifest's own schema version.

    A schema-v2 manifest (ADR 0066) spans multiple frozen pool generations,
    so it cannot be verified against a single rounds artifact: each entry
    must be checked against ITS OWN generation's pool. Callers supply
    `daily_manifest_rounds_by_generation` for that. When a v2 manifest is
    given without it, the newest generation is assumed to be the live
    `connection_rounds` -- enough to verify current dates -- and any
    generation genuinely missing an artifact is reported by the v2 validator
    itself rather than silently skipped.

    v1 manifests keep the original single-artifact path unchanged, so this
    stays backward compatible for any caller (and any Pi fleet worker) that
    has not been updated.
    """
    if (
        isinstance(daily_manifest, dict)
        and daily_manifest.get("schema_version") == CONNECTION_DAILY_MANIFEST_SCHEMA_VERSION_V2
    ):
        supplied = rounds_by_generation
        if not isinstance(supplied, dict):
            supplied = _infer_newest_generation_rounds(daily_manifest, connection_rounds)
        return connection_daily_manifest_v2_failures(daily_manifest, supplied)
    return connection_daily_manifest_failures(daily_manifest, connection_rounds)


def _infer_newest_generation_rounds(daily_manifest: Any, connection_rounds: Any) -> dict[str, Any]:
    """Best-effort fallback: map only the LAST generation to the live rounds
    artifact. Deliberately does not guess for older generations -- a wrong
    guess there would verify an archived date against a pool it was never
    frozen against, which is exactly the failure the v2 shape exists to make
    impossible."""
    generations = daily_manifest.get("generations")
    if not isinstance(generations, list) or not generations:
        return {}
    newest = generations[-1]
    if not isinstance(newest, dict):
        return {}
    generation_id = newest.get("generation_id")
    if not isinstance(generation_id, str) or not generation_id:
        return {}
    return {generation_id: connection_rounds}
