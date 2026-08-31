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

from .role_taxonomy import RoleCategory, classify_role

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
        own_roles = role_categories_by_id[contributor["artist_id"]]
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
    # Minimum hop_distance from each artist's nearest occurrence in a path/
    # round to each endpoint album -- NOT a set of "albums this artist is
    # credited on". A middle-of-path bridge artist (e.g. a mastering
    # engineer two hops from either endpoint) previously got attributed to
    # BOTH endpoint albums identically to the artists directly adjacent to
    # them, with no way for a reader to tell a direct credit from a distant
    # one. hop_distance makes that honest without dropping the (deliberately
    # kept, ADR 0048) multi-hop attribution itself.
    album_distance_by_artist: dict[int, dict[str, int]] = defaultdict(dict)
    evidence_by_artist: dict[int, set[tuple[Any, str]]] = defaultdict(set)
    neighbor_counts: dict[int, Counter[int]] = defaultdict(Counter)

    challenge_role_lookup = _credit_role_lookup(challenge.get("releases", []))

    def _record_album_distance(artist_id: int, album_id: str, distance: int) -> None:
        existing = album_distance_by_artist[artist_id].get(album_id)
        if existing is None or distance < existing:
            album_distance_by_artist[artist_id][album_id] = distance

    def record_hop(
        from_album_id: str,
        to_album_id: str,
        artist_a: int,
        artist_b: int,
        release_id: Any,
        role_a: str | None,
        role_b: str | None,
        hop_index: int,
        hop_count: int,
    ) -> None:
        # By construction each path/round is an ordered chain from the
        # from_album's representative artist (hop 0's artist_a) to the
        # to_album's representative artist (the last hop's artist_b), so a
        # participant's position in that chain gives its real hop_distance
        # to each endpoint -- not just "0, because they appear somewhere in
        # this path" as the old set-based attribution effectively assumed.
        distance_from_from = hop_index
        distance_from_to = hop_count - 1 - hop_index
        _record_album_distance(artist_a, from_album_id, distance_from_from)
        _record_album_distance(artist_a, to_album_id, distance_from_to + 1)
        _record_album_distance(artist_b, from_album_id, distance_from_from + 1)
        _record_album_distance(artist_b, to_album_id, distance_from_to)
        neighbor_counts[artist_a][artist_b] += 1
        neighbor_counts[artist_b][artist_a] += 1

        for artist_id, role, other_id in (
            (artist_a, role_a, artist_b),
            (artist_b, role_b, artist_a),
        ):
            del other_id
            role_candidates = (
                [role]
                if role is not None
                else challenge_role_lookup.get((release_id, artist_id), [])
            )
            for role_text in role_candidates:
                role_texts[artist_id][role_text] += 1
                evidence_by_artist[artist_id].add((release_id, role_text))

    for path in challenge.get("paths", []):
        hops = path.get("hops", [])
        hop_count = len(hops)
        for hop_index, hop in enumerate(hops):
            record_hop(
                str(path["from_album_id"]),
                str(path["to_album_id"]),
                int(hop["artist_a_id"]),
                int(hop["artist_b_id"]),
                hop.get("release_id"),
                role_a=None,
                role_b=None,
                hop_index=hop_index,
                hop_count=hop_count,
            )

    for round_ in routes_rounds.get("rounds", []):
        hops = round_.get("hops", [])
        hop_count = len(hops)
        for hop_index, hop in enumerate(hops):
            record_hop(
                str(round_["from_album_id"]),
                str(round_["to_album_id"]),
                int(hop["artist_a_id"]),
                int(hop["artist_b_id"]),
                hop.get("release_id"),
                role_a=hop.get("role_a"),
                role_b=hop.get("role_b"),
                hop_index=hop_index,
                hop_count=hop_count,
            )

    # Only artists both nameable and associated with at least one album --
    # an artist_id appearing in a hop but absent from every artists[] list
    # would otherwise be unrenderable; skip rather than publish a nameless page.
    all_artist_ids = sorted(set(album_distance_by_artist) & set(names))

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

        albums = sorted(
            (
                {"album_id": album_id, "hop_distance": distance}
                for album_id, distance in album_distance_by_artist[artist_id].items()
            ),
            key=lambda entry: (entry["hop_distance"], entry["album_id"]),
        )
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
