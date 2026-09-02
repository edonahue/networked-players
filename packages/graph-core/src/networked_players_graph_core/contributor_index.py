"""Build the public contributor index from already-published public
artifacts -- `challenge.v2.json`, `routes/{universe,rounds}.v1.json`, and
(ADR 0058 Slice 8) `evidence/release-registry.v1.json` -- never a fresh
full-corpus graph query. This is what keeps the index deterministic, small,
and safely publishable through the same discipline as every other artifact
under `apps/web/public/data/**`, without introducing a new dependency on
the private one-hop working set: the evidence registry is itself an
already-published artifact, not a fresh corpus query.

Every field traces to content already published in one of the source
artifacts:

- `challenge.v2.json`: `paths[].hops[]` (artist_a_id/artist_b_id/release_id)
  and `releases[].credits[]` (verbatim role_text, looked up by
  (release_id, artist_id)).
- `routes/rounds.v1.json`: `rounds[].hops[]`, which already carry
  `role_a`/`role_b` inline.
- `evidence/release-registry.v1.json`: `release_ids[]`/`years[]`, looked up
  per evidence release to derive `decade_activity` from each contributor's
  own documented releases -- not the `year` of whichever connected catalog
  album happens to anchor the hop.

Deliberately excludes anything that would require the private full/one-hop
corpus: a contributor's real full-corpus degree, or full-corpus role-text
frequency (that diagnostic lives in `role_taxonomy.py`'s local-only
`corpus_coverage_report`, never here).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from networked_players_contracts.canonical import content_hash

from .role_taxonomy import (
    RoleCategory,
    classify_role,
)

_MAX_ROLE_TEXT_EXAMPLES = 5
_MAX_EVIDENCE_ENTRIES = 10
_MAX_NEIGHBORS = 20


def contributor_index_version(contributors: list[dict[str, Any]], snapshot_date: str) -> str:
    """Order-insensitive content hash (this is a lookup index, like
    `album_art_version`, not a fingerprinted content pool): only the
    load-bearing identity fields move the version, not incidental list
    ordering."""
    identity = sorted(
        (
            {
                "artist_id": c["artist_id"],
                "name": c["name"],
                "role_categories": c["role_categories"],
                "albums": c["albums"],
                "evidence": c["evidence"],
            }
            for c in contributors
        ),
        key=lambda c: c["artist_id"],
    )
    digest = content_hash(identity, length=12)
    return f"contributor-index-v1-{snapshot_date}-{digest}"


def album_hop_distances_version(entries: list[dict[str, Any]], snapshot_date: str) -> str:
    """Same discipline as `contributor_index_version`: an order-insensitive
    content hash of a lookup artifact, not a fingerprinted content pool."""
    identity = sorted(
        (
            {
                "artist_id": e["artist_id"],
                "album_id": e["album_id"],
                "hop_distance": e["hop_distance"],
            }
            for e in entries
        ),
        key=lambda e: (e["artist_id"], e["album_id"]),
    )
    digest = content_hash(identity, length=12)
    return f"album-hop-distances-v1-{snapshot_date}-{digest}"


def _credit_role_lookup(releases: list[dict[str, Any]]) -> dict[tuple[Any, int], list[str]]:
    """(release_id, artist_id) -> verbatim role_text values from linked
    credits on that release, in `challenge.v2.json`'s `releases[]` shape."""
    lookup: dict[tuple[Any, int], list[str]] = defaultdict(list)
    for release in releases:
        release_id = release.get("release_id")
        for credit in release.get("credits", []):
            if not credit.get("is_linked"):
                continue
            artist_id = credit.get("artist_id")
            role_text = credit.get("role_text")
            if artist_id is None or role_text is None:
                continue
            lookup[(release_id, artist_id)].append(role_text)
    return lookup


def _decade(year: int) -> int:
    return (year // 10) * 10


def _compute_album_distances(
    challenge: dict[str, Any], routes_rounds: dict[str, Any]
) -> dict[int, dict[str, int]]:
    """artist_id -> {album_id -> minimum hop_distance}, walking every path/
    round's hops in order. By construction each path/round is an ordered
    chain from the from_album's representative artist (hop 0's artist_a) to
    the to_album's representative artist (the last hop's artist_b), so a
    participant's position in that chain gives its real distance to each
    endpoint. Shared by `build_contributor_index` (which only needs the
    plain album-id set, for `albums[]`) and `build_album_hop_distances`
    (which needs the full distances) -- ADR 0048 addendum: a companion
    artifact, not a field grafted onto `contributor-index-v1`, because that
    exact-key-set contract is validated as an all-or-nothing whole (see the
    addendum for why a new required key on an unversioned "v1" artifact is a
    real breaking change, not just a client-compatibility question)."""
    album_distance_by_artist: dict[int, dict[str, int]] = defaultdict(dict)

    def _record(artist_id: int, album_id: str, distance: int) -> None:
        existing = album_distance_by_artist[artist_id].get(album_id)
        if existing is None or distance < existing:
            album_distance_by_artist[artist_id][album_id] = distance

    def _walk(
        from_album_id: str,
        to_album_id: str,
        artist_a: int,
        artist_b: int,
        hop_index: int,
        hop_count: int,
    ) -> None:
        distance_from_from = hop_index
        distance_from_to = hop_count - 1 - hop_index
        _record(artist_a, from_album_id, distance_from_from)
        _record(artist_a, to_album_id, distance_from_to + 1)
        _record(artist_b, from_album_id, distance_from_from + 1)
        _record(artist_b, to_album_id, distance_from_to)

    for path in challenge.get("paths", []):
        hops = path.get("hops", [])
        hop_count = len(hops)
        for hop_index, hop in enumerate(hops):
            _walk(
                str(path["from_album_id"]),
                str(path["to_album_id"]),
                int(hop["artist_a_id"]),
                int(hop["artist_b_id"]),
                hop_index,
                hop_count,
            )

    for round_ in routes_rounds.get("rounds", []):
        hops = round_.get("hops", [])
        hop_count = len(hops)
        for hop_index, hop in enumerate(hops):
            _walk(
                str(round_["from_album_id"]),
                str(round_["to_album_id"]),
                int(hop["artist_a_id"]),
                int(hop["artist_b_id"]),
                hop_index,
                hop_count,
            )

    return album_distance_by_artist


def _annotate_interesting_next_step(contributors: list[dict[str, Any]]) -> None:
    """ADR 0060: a deterministic, source-derived `interesting_next_step` per
    contributor -- among their own (already capped, already computed)
    `neighboring_contributor_ids`, the one whose `role_categories` are
    ENTIRELY DISJOINT from this contributor's own. That is a real structural
    fact (a genuinely different kind of credited collaborator, not more of
    the same), not an inferred claim about interest, importance, or
    influence -- `reason` says exactly and only that.

    Deliberately never ranks by `connection_count` (the measured, real
    reason ADR 0059 killed the old Connect route scorer: degree correlates
    with fame, and a "most connected" pick would always point toward the
    same handful of hub contributors). Where a role-disjoint neighbor
    exists, `connection_count` breaks a tie -- LOWEST first, a deliberate
    anti-hub choice that favors a lesser-explored contributor over a hub,
    never the other way around. `artist_id` is the final, fully
    deterministic tie-break.

    `None` when no neighbor qualifies (measured: happens for about 31% of
    real contributors with 2+ neighbors) -- never a fabricated pick just to
    fill the field."""
    role_categories_by_id = {c["artist_id"]: set(c["role_categories"]) for c in contributors}
    connection_count_by_id = {c["artist_id"]: c["connection_count"] for c in contributors}

    for contributor in contributors:
        own_id = contributor["artist_id"]
        own_roles = role_categories_by_id[own_id]
        candidates = []
        for neighbor_id in contributor["neighboring_contributor_ids"]:
            neighbor_roles = role_categories_by_id.get(neighbor_id)
            if neighbor_roles is None:
                continue  # a neighbor absent from this index (never rendered) can't be suggested
            if own_roles.isdisjoint(neighbor_roles):
                candidates.append(neighbor_id)

        if not candidates:
            contributor["interesting_next_step"] = None
            continue

        candidates.sort(key=lambda cid: (connection_count_by_id[cid], cid))
        chosen_id = candidates[0]
        contributor["interesting_next_step"] = {
            "artist_id": chosen_id,
            "reason": "credited in a different kind of role than this contributor",
        }


def build_contributor_index(
    *,
    challenge: dict[str, Any],
    routes_universe: dict[str, Any],
    routes_rounds: dict[str, Any],
    catalog: dict[str, Any],
    evidence_release_registry: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Deterministic given the same five already-published artifacts. Raises
    `ValueError` if the challenge/routes artifacts don't agree with the
    catalog's own `catalog_version` -- a contributor index belongs to exactly
    one catalog generation, the same rule `album_art_failures` enforces.

    `evidence_release_registry` (ADR 0058 Slice 3, itself an already-published
    artifact -- this doesn't touch the private one-hop corpus) supplies each
    contributor's `decade_activity`: their own evidence releases' real years,
    not the `year` of whichever connected catalog album happens to anchor the
    hop. A contributor whose only documented evidence predates or postdates
    the anchor album's own release year previously got bucketed under the
    wrong decade; see `test_contributor_index.py`'s year-mismatch fixture."""
    catalog_version = catalog["catalog_version"]
    snapshot_date = catalog["snapshot_date"]

    for label, artifact in (
        ("challenge", challenge),
        ("routes_universe", routes_universe),
        ("routes_rounds", routes_rounds),
    ):
        artifact_catalog_version = artifact.get("provenance", {}).get("catalog_version")
        if artifact_catalog_version != catalog_version:
            raise ValueError(
                f"{label}'s catalog_version {artifact_catalog_version!r} does not match "
                f"the catalog's catalog_version {catalog_version!r}"
            )

    release_years: dict[Any, int | None] = dict(
        zip(
            evidence_release_registry.get("release_ids", []),
            evidence_release_registry.get("years", []),
            strict=True,
        )
    )

    names: dict[int, str] = {}
    for artist in challenge.get("artists", []):
        names[int(artist["artist_id"])] = str(artist["name"])
    for artist in routes_rounds.get("artists", []):
        names.setdefault(int(artist["artist_id"]), str(artist["name"]))

    role_texts: dict[int, Counter[str]] = defaultdict(Counter)
    albums_by_artist = _compute_album_distances(challenge, routes_rounds)
    evidence_by_artist: dict[int, set[tuple[Any, str]]] = defaultdict(set)
    neighbor_counts: dict[int, Counter[int]] = defaultdict(Counter)
    challenge_role_lookup = _credit_role_lookup(challenge.get("releases", []))

    def record_hop(
        artist_a: int,
        artist_b: int,
        release_id: Any,
        role_a: str | None,
        role_b: str | None,
    ) -> None:
        neighbor_counts[artist_a][artist_b] += 1
        neighbor_counts[artist_b][artist_a] += 1

        for artist_id, role in ((artist_a, role_a), (artist_b, role_b)):
            role_candidates = (
                [role]
                if role is not None
                else challenge_role_lookup.get((release_id, artist_id), [])
            )
            for role_text in role_candidates:
                role_texts[artist_id][role_text] += 1
                evidence_by_artist[artist_id].add((release_id, role_text))

    for path in challenge.get("paths", []):
        for hop in path.get("hops", []):
            record_hop(
                int(hop["artist_a_id"]),
                int(hop["artist_b_id"]),
                hop.get("release_id"),
                role_a=None,
                role_b=None,
            )

    for round_ in routes_rounds.get("rounds", []):
        for hop in round_.get("hops", []):
            record_hop(
                int(hop["artist_a_id"]),
                int(hop["artist_b_id"]),
                hop.get("release_id"),
                role_a=hop.get("role_a"),
                role_b=hop.get("role_b"),
            )

    # Only artists both nameable and associated with at least one album --
    # an artist_id appearing in a hop but absent from every artists[] list
    # would otherwise be unrenderable; skip rather than publish a nameless page.
    all_artist_ids = sorted(set(albums_by_artist) & set(names))

    contributors: list[dict[str, Any]] = []
    for artist_id in all_artist_ids:
        role_counter = role_texts.get(artist_id, Counter())
        categories: set[RoleCategory] = set()
        for role_text in role_counter:
            categories.update(classify_role(role_text))
        known_categories = categories - {RoleCategory.UNKNOWN}
        role_categories = (
            known_categories if known_categories else categories or {RoleCategory.UNKNOWN}
        )

        role_text_examples = [
            text
            for text, _count in sorted(role_counter.items(), key=lambda item: (-item[1], item[0]))[
                :_MAX_ROLE_TEXT_EXAMPLES
            ]
        ]

        albums = sorted(albums_by_artist[artist_id])
        evidence_release_ids = {
            release_id for release_id, _role_text in evidence_by_artist.get(artist_id, set())
        }
        years = [
            release_years[release_id]
            for release_id in evidence_release_ids
            if release_years.get(release_id) is not None
        ]
        decades = sorted({_decade(year) for year in years if year is not None})

        neighbors = neighbor_counts.get(artist_id, Counter())
        neighboring_contributor_ids = [
            neighbor_id
            for neighbor_id, _count in sorted(
                neighbors.items(), key=lambda item: (-item[1], item[0])
            )[:_MAX_NEIGHBORS]
        ]

        evidence = [
            {"release_id": release_id, "role_text": role_text}
            for release_id, role_text in sorted(
                evidence_by_artist.get(artist_id, set()), key=lambda e: (str(e[0]), e[1])
            )[:_MAX_EVIDENCE_ENTRIES]
        ]

        contributors.append(
            {
                "artist_id": artist_id,
                "name": names[artist_id],
                "role_categories": sorted(c.value for c in role_categories),
                "role_text_examples": role_text_examples,
                "albums": albums,
                "decade_activity": decades,
                "connection_count": len(neighbors),
                "neighboring_contributor_ids": neighboring_contributor_ids,
                "evidence": evidence,
            }
        )

    contributors.sort(key=lambda c: c["artist_id"])
    _annotate_interesting_next_step(contributors)
    index_version = contributor_index_version(contributors, snapshot_date)

    return {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "contributor_index_version": index_version,
        "generated_at": generated_at,
        "source": (
            "Derived from apps/web/public/data/challenge.v2.json, "
            "apps/web/public/data/routes/{universe,rounds}.v1.json, and "
            "apps/web/public/data/evidence/release-registry.v1.json (decade_activity only) "
            "-- no fresh full-corpus graph query. See docs/DATA_AND_RIGHTS.md."
        ),
        "license": (
            "Derived from the Discogs monthly CC0 data dumps via the three published "
            "artifacts above. See docs/DATA_AND_RIGHTS.md."
        ),
        "contributors": contributors,
    }


def build_album_hop_distances(
    *,
    challenge: dict[str, Any],
    routes_rounds: dict[str, Any],
    catalog: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """ADR 0048 addendum: a companion artifact to `contributor-index-v1`,
    deliberately NOT a field on it. `contributor-index-v1`'s contract is
    validated as an exact key set; adding a new required key would reject
    every already-published v1 file under old validator code and would be
    rejected itself by any external consumer that pinned the documented v1
    key list -- a real breaking change hiding behind an unchanged
    `schema_version`. This is instead a wholly separate, independently
    versioned artifact (same pattern as ADR 0058's evidence-release-registry
    alongside `contributor-index-v1`), so neither file's existing contract
    ever changes shape.

    Same inclusion rule as `build_contributor_index`: only contributors both
    nameable and associated with at least one album. Raises `ValueError` on
    a `catalog_version` mismatch, the same rule every other artifact here
    enforces."""
    catalog_version = catalog["catalog_version"]
    snapshot_date = catalog["snapshot_date"]

    for label, artifact in (("challenge", challenge), ("routes_rounds", routes_rounds)):
        artifact_catalog_version = artifact.get("provenance", {}).get("catalog_version")
        if artifact_catalog_version != catalog_version:
            raise ValueError(
                f"{label}'s catalog_version {artifact_catalog_version!r} does not match "
                f"the catalog's catalog_version {catalog_version!r}"
            )

    names: dict[int, str] = {}
    for artist in challenge.get("artists", []):
        names[int(artist["artist_id"])] = str(artist["name"])
    for artist in routes_rounds.get("artists", []):
        names.setdefault(int(artist["artist_id"]), str(artist["name"]))

    album_distance_by_artist = _compute_album_distances(challenge, routes_rounds)
    all_artist_ids = sorted(set(album_distance_by_artist) & set(names))

    entries: list[dict[str, Any]] = [
        {"artist_id": artist_id, "album_id": album_id, "hop_distance": distance}
        for artist_id in all_artist_ids
        for album_id, distance in sorted(
            album_distance_by_artist[artist_id].items(),
            key=lambda item: (item[1], item[0]),
        )
    ]

    version = album_hop_distances_version(entries, snapshot_date)

    return {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "album_hop_distances_version": version,
        "generated_at": generated_at,
        "source": (
            "Derived from apps/web/public/data/challenge.v2.json and "
            "apps/web/public/data/routes/rounds.v1.json -- companion artifact to "
            "contributor-index-v1 (ADR 0048 addendum), never a fresh full-corpus query."
        ),
        "license": (
            "Derived from the Discogs monthly CC0 data dumps via the two published "
            "artifacts above. See docs/DATA_AND_RIGHTS.md."
        ),
        "entries": entries,
    }
