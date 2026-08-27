"""Resolve public editorial album queries against a parsed Discogs snapshot.

**Why this exists, distinct from the private seed.** `expand_one_hop`'s
frontier comes entirely from `data/private/discogs-seed.json` -- release IDs
derived from the operator's own collection. That is deliberate (ADR 0011):
the private seed is an ownership signal, never an editorial one. But a public
album someone wants to add to the catalog need not be something the operator
owns. Half of Phase 7's Bucket A personal picks and effectively all of its
graph-rich candidates are outside the private seed's one-hop reach for
exactly this reason -- resolvable in the FULL parsed snapshot, absent from
the one-hop working set built from it.

This module is the resolution half of the fix: given a small, human-curated
list of `{artist, title}` queries (optionally pinned by `master_id` when the
identity is already known -- e.g. hand-verified against the real snapshot, as
Phase 7's Bucket A was), resolve each to a real release/master/artist
identity in the FULL snapshot and report eligibility. It does **not** decide
whether an album should be published -- that stays `build-public-album-catalog`'s
job, gated by the real release-format policy at build time. This command
reports what it can check now (curated exclusions, the master genre/style
gate when masters are attached) and says plainly what it cannot (the
release-format descriptor gate, which needs a `release_formats` table this
command's own dataset -- the full snapshot -- does not carry).

The `resolve()` output becomes `data/albums/editorial-seed-v1.json` -- a
COMMITTED, PUBLIC file. Unlike the private seed, this is meant to be read:
it names exactly which albums are editorial expansion candidates, with their
real Discogs identities. See `docs/PUBLIC_PRIVATE_BOUNDARY.md` and
`data/contracts/editorial-seed-v1.md`.

Never guesses: a query that doesn't resolve, resolves ambiguously, or fails a
checkable policy is reported in `unresolved` with a reason, never silently
dropped or substituted.
"""

from __future__ import annotations

import json
from typing import Any

from .album_policy import master_non_studio_reason
from .challenge import _year_from_released
from .graph import CreditGraph

EDITORIAL_SEED_SCHEMA_VERSION = 1
EDITORIAL_SEED_KIND = "public-editorial-seed"

_ALBUM_KEYS = frozenset(
    {
        "query_artist",
        "query_title",
        "master_id",
        "main_release_id",
        "artist_id",
        "artist",
        "title",
        "year",
    }
)
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "snapshot_date",
        "generated_by",
        "generated_at",
        "note",
        "albums",
    }
)
_FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")


def resolve_editorial_albums(
    graph: CreditGraph,
    queries: list[dict[str, Any]],
    *,
    master_exclusions: frozenset[int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Resolve each query to a real identity, or explain why it did not.

    A query is `{"artist": str, "title": str}` for a text match, or may add
    `"master_id": int` to resolve by exact identity instead (preferred when
    known -- text matching on Discogs' own inconsistent punctuation, e.g. a
    curly vs. straight quote in `Sign "O" The Times`, is a real failure mode
    a pinned ID sidesteps entirely). `master_id` takes precedence when both
    are given; `artist` is still passed through as an `artist_hint` to guard
    against a master_id resolving to an unexpected billed artist.

    Two albums resolving to the same `master_id` is treated as a duplicate,
    not two entries -- the second occurrence goes to `unresolved` with a
    reason naming the first. Order in `queries` therefore matters: put the
    entry you want kept first.
    """
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    seen_master_ids: set[int] = set()

    for query in queries:
        artist_query = query.get("artist")
        title_query = query.get("title")
        master_hint = query.get("master_id")

        if master_hint is not None:
            found = graph.find_release_by_id_hint(
                master_id=int(master_hint), artist_hint=artist_query
            )
        elif artist_query and title_query:
            found = graph.find_release_by_title_artist(title_query, artist_query)
        else:
            unresolved.append(
                {**query, "reason": "query needs master_id, or both artist and title"}
            )
            continue

        if found is None:
            unresolved.append({**query, "reason": "no matching release in this snapshot"})
            continue

        master_id = found["master_id"]
        if master_id is not None and master_id in seen_master_ids:
            unresolved.append(
                {
                    **query,
                    "master_id": master_id,
                    "reason": f"duplicate: master_id {master_id} already resolved earlier",
                }
            )
            continue

        master = graph.master(master_id) if master_id is not None else None
        eligibility: dict[str, Any] = {}
        exclusion_reason: str | None = None

        if master_exclusions and master_id in (master_exclusions or frozenset()):
            exclusion_reason = "curated studio-album-master-exclusions-v1 entry"
            eligibility["curated_exclusion"] = True

        if master is not None:
            non_studio_reason = master_non_studio_reason(master["genres"], master["styles"])
            if non_studio_reason:
                exclusion_reason = exclusion_reason or f"non-studio master: {non_studio_reason}"
                eligibility["non_studio_genre_reason"] = non_studio_reason
        elif master_id is not None:
            eligibility["genre_style_gate"] = "not checked -- graph opened without --masters-root"

        eligibility["release_format_gate"] = (
            "not checked by this command -- this dataset has no release_formats table; "
            "applied fail-closed by build-public-album-catalog at build time"
        )

        if exclusion_reason is not None:
            unresolved.append(
                {
                    **query,
                    "master_id": master_id,
                    "reason": exclusion_reason,
                    "eligibility": eligibility,
                }
            )
            continue

        main_release_id = master["main_release_id"] if master is not None else found["release_id"]
        year = (
            int(master["year"])
            if master is not None and master["year"]
            else _year_from_released(found.get("released"))
        )
        title = master["title"] if master is not None and master["title"] else found["title"]

        entry = {
            "query_artist": artist_query,
            "query_title": title_query,
            "master_id": master_id,
            "main_release_id": main_release_id,
            "artist_id": found["artist_id"],
            "artist": found["name"],
            "title": title,
            "year": year,
            "eligibility": eligibility,
        }
        if master_id is not None:
            seen_master_ids.add(master_id)
        resolved.append(entry)

    return {"resolved": resolved, "unresolved": unresolved}


def editorial_seed_release_ids(payload: dict[str, Any]) -> list[int]:
    """The deduplicated, sorted release IDs a committed editorial-seed
    artifact contributes to one-hop expansion -- always `main_release_id`,
    never a query's raw text, matching `expand_one_hop`'s own release-ID
    seed shape so the two seed kinds can be unioned without special-casing
    either one downstream."""
    ids = {int(album["main_release_id"]) for album in payload.get("albums", [])}
    return sorted(ids)


def editorial_seed_failures(payload: dict[str, Any]) -> list[str]:
    """Structural checks on a committed `data/albums/editorial-seed-v1.json`.

    This file is a build INPUT, not an `apps/web/public/data/**` artifact, so
    it deliberately does not live in `packages/contracts` alongside the
    dependency-free web-artifact validators -- nothing here needs to run on a
    Pi or ship in the web build. What it must still guarantee, because this
    file is committed and public: exactly the documented key set (an
    `eligibility` dict leaking in from `resolve_editorial_albums`'s return
    value would publish policy-check detail the contract doesn't promise),
    and none of the forbidden substrings/phrases every other public-facing
    artifact in this project is scanned for.
    """
    if not isinstance(payload, dict):
        return ["payload must be an object"]

    failures: list[str] = []
    if set(payload.keys()) != _TOP_LEVEL_KEYS:
        failures.append(f"unexpected top-level keys: {sorted(payload.keys())}")
    if payload.get("schema_version") != EDITORIAL_SEED_SCHEMA_VERSION:
        failures.append(f"schema_version must be {EDITORIAL_SEED_SCHEMA_VERSION}")
    if payload.get("kind") != EDITORIAL_SEED_KIND:
        failures.append(f"kind must be {EDITORIAL_SEED_KIND!r}")
    if not payload.get("snapshot_date"):
        failures.append("snapshot_date is required")

    albums = payload.get("albums")
    if not isinstance(albums, list):
        failures.append("albums must be an array")
        albums = []
    for index, album in enumerate(albums):
        if not isinstance(album, dict):
            failures.append(f"albums[{index}] must be an object")
            continue
        if set(album.keys()) != _ALBUM_KEYS:
            failures.append(f"albums[{index}] has unexpected keys: {sorted(album.keys())}")
        if album.get("main_release_id") is None:
            failures.append(f"albums[{index}].main_release_id is required")
        if album.get("artist_id") is None:
            failures.append(f"albums[{index}].artist_id is required")

    master_ids = [a.get("master_id") for a in albums if isinstance(a, dict) and a.get("master_id")]
    if len(master_ids) != len(set(master_ids)):
        failures.append("albums contains a duplicate master_id")

    serialized = json.dumps(payload)
    failures.extend(
        f"payload contains forbidden substring: {forbidden!r}"
        for forbidden in _FORBIDDEN_SUBSTRINGS
        if forbidden in serialized
    )
    return failures
