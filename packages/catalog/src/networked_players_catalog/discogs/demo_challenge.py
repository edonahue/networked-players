"""Build a small, curated, real challenge.v1.json artifact from cached Discogs
API release responses. See ADR 0012 -- this is a detour ahead of the formal
monthly-dump pipeline (BUILD_PLAN.md Milestones 3/5/6/7/8), not a replacement.

Design decision: a credit is only promoted to track_artist/track_credit scope
when the API response genuinely nests artists/extraartists under an individual
tracklist[] entry -- mirroring how the XML dump parser derives track scope from
real document nesting, never by parsing the free-text `tracks` field (e.g.
"1-2"). A release-level extraartist with a non-empty `tracks` string but no
nested per-track entry stays release_credit scope, with `credited_tracks_text`
populated verbatim: evidence is preserved, not silently dropped, but not
over-claimed as track-resolved either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from networked_players_catalog import __version__

from .parquet import SCHEMA_VERSION

API_BASE_URL = "https://api.discogs.com"

# Discogs reserves artist ID 194 for "Various" -- a compilation placeholder, not an
# individual. Treat it like an unlinked credit (evidence, never a playable identity or
# graph node) so a published path never reads as a "connection" to a non-person.
NON_INDIVIDUAL_ARTIST_IDS = frozenset({194})


def _artist_credit_row(
    artist: dict[str, Any],
    *,
    snapshot_date: str,
    release_id: int,
    scope: str,
    track_index: int | None = None,
    track_path: str | None = None,
    track_position: str | None = None,
    track_title: str | None = None,
) -> dict[str, Any]:
    raw_id = artist.get("id")
    artist_id = (
        int(raw_id)
        if isinstance(raw_id, int) and raw_id > 0 and raw_id not in NON_INDIVIDUAL_ARTIST_IDS
        else None
    )
    return {
        "snapshot_date": snapshot_date,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": track_path,
        "track_position": track_position,
        "track_title": track_title,
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": artist.get("name") or "",
        "anv": artist.get("anv") or None,
        "join_text": artist.get("join") or None,
        "role_text": artist.get("role") or None,
        "credited_tracks_text": artist.get("tracks") or None,
        "is_linked": artist_id is not None,
        "playable_identity": artist_id is not None,
    }


def _images(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("images") or []
    ordered = sorted(raw, key=lambda img: 0 if img.get("type") == "primary" else 1)
    images: list[dict[str, Any]] = []
    for image in ordered:
        uri, uri150 = image.get("uri"), image.get("uri150")
        if not uri or not uri150:
            continue
        images.append(
            {
                "uri": uri,
                "uri150": uri150,
                "width": int(image.get("width") or 0),
                "height": int(image.get("height") or 0),
            }
        )
    return images


def parse_api_release(payload: dict[str, Any], *, snapshot_date: str) -> dict[str, Any]:
    """Normalize one raw /releases/{id} response into the Release/Credit shape."""
    release_id = int(payload["id"])
    released = payload.get("released") or (str(payload["year"]) if payload.get("year") else None)
    # Prefer the human-browsable page URL ("uri") for the evidence link PathCard renders.
    source_url = payload.get("uri") or f"https://www.discogs.com/release/{release_id}"

    release: dict[str, Any] = {
        "snapshot_date": snapshot_date,
        "release_id": release_id,
        "status": payload.get("status") or "Unknown",
        "title": payload.get("title") or "",
        "country": payload.get("country") or None,
        "released": released,
        "master_id": payload.get("master_id") or None,
        "master_is_main_release": None,  # not derivable from a single release response
        "data_quality": payload.get("data_quality") or None,
        "source_url": source_url,
        "images": _images(payload),
    }

    credits: list[dict[str, Any]] = []
    for artist in payload.get("artists") or []:
        credits.append(
            _artist_credit_row(
                artist, snapshot_date=snapshot_date, release_id=release_id, scope="release_artist"
            )
        )
    for artist in payload.get("extraartists") or []:
        credits.append(
            _artist_credit_row(
                artist, snapshot_date=snapshot_date, release_id=release_id, scope="release_credit"
            )
        )
    for track_index, track in enumerate(payload.get("tracklist") or []):
        position, title = track.get("position") or None, track.get("title") or None
        track_path = str(track_index)
        for artist in track.get("artists") or []:
            credits.append(
                _artist_credit_row(
                    artist,
                    snapshot_date=snapshot_date,
                    release_id=release_id,
                    scope="track_artist",
                    track_index=track_index,
                    track_path=track_path,
                    track_position=position,
                    track_title=title,
                )
            )
        for artist in track.get("extraartists") or []:
            credits.append(
                _artist_credit_row(
                    artist,
                    snapshot_date=snapshot_date,
                    release_id=release_id,
                    scope="track_credit",
                    track_index=track_index,
                    track_path=track_path,
                    track_position=position,
                    track_title=title,
                )
            )

    release["credits"] = credits
    return release


# --- Graph + curation --------------------------------------------------------


@dataclass(slots=True)
class Hop:
    release_id: int
    artist_a_id: int
    artist_b_id: int


@dataclass(slots=True)
class Candidate:
    from_artist_id: int
    to_artist_id: int
    hops: list[Hop]
    score: float


def build_adjacency(releases: list[dict[str, Any]]) -> dict[int, dict[int, list[int]]]:
    """artist_id -> {other_artist_id -> [release_id, ...]}, from shared *linked* credits."""
    adjacency: dict[int, dict[int, list[int]]] = {}
    for release in releases:
        linked = sorted({c["artist_id"] for c in release["credits"] if c["playable_identity"]})
        for i, a in enumerate(linked):
            for b in linked[i + 1 :]:
                adjacency.setdefault(a, {}).setdefault(b, []).append(release["release_id"])
                adjacency.setdefault(b, {}).setdefault(a, []).append(release["release_id"])
    return adjacency


def top_connected_artists(
    adjacency: dict[int, dict[int, list[int]]], *, count: int = 10
) -> list[int]:
    return [a for a, _ in sorted(adjacency.items(), key=lambda kv: len(kv[1]), reverse=True)][
        :count
    ]


def _evidence_rows(release: dict[str, Any], artist_ids: set[int]) -> list[dict[str, Any]]:
    return [c for c in release["credits"] if c["artist_id"] in artist_ids]


def _score_hop(release_by_id: dict[int, dict[str, Any]], hop: Hop) -> float:
    """A simple evidence-richness heuristic -- not a claim of 'best' path."""
    release = release_by_id[hop.release_id]
    evidence = _evidence_rows(release, {hop.artist_a_id, hop.artist_b_id})
    role_diversity = len({c["role_text"] for c in evidence if c["role_text"]})
    track_scope_bonus = sum(
        1 for c in evidence if c["credit_scope"] in ("track_artist", "track_credit")
    )
    return len(evidence) + role_diversity + 0.5 * track_scope_bonus


def find_candidate_paths(
    adjacency: dict[int, dict[int, list[int]]],
    release_by_id: dict[int, dict[str, Any]],
    *,
    seed_artist_ids: list[int],
) -> list[Candidate]:
    """1-hop and 2-hop candidates from each seed artist. Simple BFS, not exhaustive."""
    candidates: list[Candidate] = []
    seen_pairs: set[tuple[int, int]] = set()
    for source in seed_artist_ids:
        for neighbor, release_ids in adjacency.get(source, {}).items():
            pair: tuple[int, int] = (min(source, neighbor), max(source, neighbor))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            hop = Hop(release_ids[0], source, neighbor)
            candidates.append(Candidate(source, neighbor, [hop], _score_hop(release_by_id, hop)))
        for bridge, first_ids in adjacency.get(source, {}).items():
            for target, second_ids in adjacency.get(bridge, {}).items():
                if target == source:
                    continue
                pair = (min(source, target), max(source, target))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                hop1 = Hop(first_ids[0], source, bridge)
                hop2 = Hop(second_ids[0], bridge, target)
                score = _score_hop(release_by_id, hop1) + _score_hop(release_by_id, hop2)
                candidates.append(Candidate(source, target, [hop1, hop2], score))
    return candidates


def curate_paths(candidates: list[Candidate], *, limit: int = 8) -> list[Candidate]:
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    selected: list[Candidate] = []
    used_endpoints: set[tuple[int, int]] = set()
    for candidate in ranked:
        pair: tuple[int, int] = (
            min(candidate.from_artist_id, candidate.to_artist_id),
            max(candidate.from_artist_id, candidate.to_artist_id),
        )
        if pair in used_endpoints:
            continue
        used_endpoints.add(pair)
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _name_for(releases_by_id: dict[int, dict[str, Any]], artist_id: int) -> str:
    """The artist's own canonical name -- not whichever ANV a single credit happened to use.

    ANV is a per-credit display override (evidence for that specific line), not the
    artist's identity; an artist-level label (path endpoints, the roster) should stay
    consistent even when different releases credit them under different ANVs.
    """
    for release in releases_by_id.values():
        for credit in release["credits"]:
            if credit["artist_id"] == artist_id:
                return str(credit["name"] or credit["anv"])
    return f"Artist {artist_id}"


def _describe(candidate: Candidate, releases_by_id: dict[int, dict[str, Any]]) -> str:
    if len(candidate.hops) == 1:
        return "Two artists credited on the same release."
    bridge_name = _name_for(releases_by_id, candidate.hops[0].artist_b_id)
    return f"Two documented hops, bridged by {bridge_name}."


def build_challenge(
    releases_by_id: dict[int, dict[str, Any]],
    *,
    snapshot_date: str,
    generated_by: str,
    max_paths: int = 8,
    seed_count: int = 10,
) -> dict[str, Any]:
    releases = list(releases_by_id.values())
    adjacency = build_adjacency(releases)
    if not adjacency:
        raise ValueError("no co-credited linked-artist pairs found across the fetched releases")

    seeds = top_connected_artists(adjacency, count=seed_count)
    candidates = find_candidate_paths(adjacency, releases_by_id, seed_artist_ids=seeds)
    curated = curate_paths(candidates, limit=max_paths)
    if not curated:
        raise ValueError("no candidate paths found -- widen seed_count or check input data")

    used_release_ids: set[int] = set()
    used_artist_ids: set[int] = set()
    paths_json: list[dict[str, Any]] = []
    for index, candidate in enumerate(curated, start=1):
        for hop in candidate.hops:
            used_release_ids.add(hop.release_id)
            used_artist_ids.update((hop.artist_a_id, hop.artist_b_id))
        paths_json.append(
            {
                "id": f"path-{index:02d}",
                "label": (
                    f"{_name_for(releases_by_id, candidate.from_artist_id)} → "
                    f"{_name_for(releases_by_id, candidate.to_artist_id)}"
                ),
                "description": _describe(candidate, releases_by_id),
                "from_artist_id": candidate.from_artist_id,
                "to_artist_id": candidate.to_artist_id,
                "hops": [
                    {
                        "release_id": h.release_id,
                        "artist_a_id": h.artist_a_id,
                        "artist_b_id": h.artist_b_id,
                    }
                    for h in candidate.hops
                ],
            }
        )

    releases_json = [releases_by_id[rid] for rid in sorted(used_release_ids)]
    artist_names: dict[int, str] = {}
    for release in releases_json:
        for credit in release["credits"]:
            aid = credit["artist_id"]
            if aid in used_artist_ids and aid not in artist_names:
                artist_names[aid] = credit["name"] or credit["anv"]
    artists_json = [
        {"artist_id": aid, "name": artist_names[aid]} for aid in sorted(used_artist_ids)
    ]

    return {
        "schema_version": 1,
        "provenance": {
            "source": "Discogs API (api.discogs.com), release endpoint",
            "license": (
                "Individual release records are Discogs user-contributed catalog data "
                "(not CC0 like the monthly dumps); retrieved via the authenticated API "
                "under Discogs API Terms of Service. See docs/DATA_AND_RIGHTS.md."
            ),
            "snapshot_date": snapshot_date,
            "source_url": f"{API_BASE_URL}/releases/{{release_id}}",
            "generated_by": generated_by,
            "catalog_parser_version": __version__,
            "catalog_schema_version": SCHEMA_VERSION,
            "note": (
                f"Real Discogs data for a small, curated subset -- {len(releases_json)} "
                f"releases and {len(paths_json)} paths -- not the full private seed. The "
                "private seed and full API response cache are never published. See ADR 0012."
            ),
        },
        "releases": releases_json,
        "artists": artists_json,
        "paths": paths_json,
    }
