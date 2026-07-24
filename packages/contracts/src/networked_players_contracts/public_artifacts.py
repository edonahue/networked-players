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
from .catalog import public_album_catalog_failures
from .challenge import challenge_failures
from .connection_daily_manifest import connection_daily_manifest_failures
from .connection_rounds import connection_rounds_failures
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
)


def public_artifacts_failures(
    *,
    catalog: Any,
    album_art: Any,
    connection_universe: Any,
    connection_rounds: Any,
    daily_manifest: Any,
    routes_universe: Any,
    routes_rounds: Any,
    challenge: Any,
) -> dict[str, list[str]]:
    """Every contract failure across the whole real-artifact publication set,
    grouped by artifact. Every key in `PUBLIC_ARTIFACT_GROUPS` is always
    present, with an empty list when that artifact is clean -- callers can
    report "N/N clean" without special-casing an absent key."""
    return {
        "catalog": public_album_catalog_failures(catalog),
        "album_art_registry": album_art_failures(album_art, catalog),
        "connection_guesser": connection_rounds_failures(connection_universe, connection_rounds),
        "connection_daily_manifest": connection_daily_manifest_failures(
            daily_manifest, connection_rounds
        ),
        "record_routes": record_routes_failures(routes_universe, routes_rounds),
        "challenge": challenge_failures(challenge, catalog),
    }
