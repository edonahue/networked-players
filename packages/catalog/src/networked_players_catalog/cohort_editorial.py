"""Transparent, local-only editorial ranking for a scored cohort."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from networked_players_graph_core.graph import edge_ineligible_role

# Given a release_id and the artist ids on a hop, return that release's row (or
# None) and its credit rows for those artists -- exactly `CreditGraph.release`
# and `CreditGraph.credit_rows`. Injected rather than imported so the ranking
# stays a pure function of its inputs and can be tested without a dataset.
EvidenceLookup = Callable[[int, set[int]], tuple[dict[str, Any] | None, list[dict[str, Any]]]]


def _album_map(resolved: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"master-{item['master_id']}": item for item in resolved.get("resolved", [])}


def _year(released: Any) -> str | None:
    """The year from a Discogs `released` value ("1991", "1991-09-24")."""
    text = str(released or "").strip()
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else None


def _display_name(rows: list[dict[str, Any]], artist_id: int) -> str:
    """The artist's own credited name on this release. Display only -- identity
    is always `artist_id` (ADR 0035)."""
    for row in rows:
        if row["artist_id"] == artist_id and row.get("name"):
            return str(row["name"])
    return f"artist {artist_id}"


def explain_hop(hop: dict[str, Any], lookup: EvidenceLookup) -> dict[str, Any]:
    """Turn one scored hop into the evidence a human needs to judge it: which
    release, which recording, who is credited on it, and in what role.

    A hop's `quality_flags` already say *which rule* admitted the edge; this
    says *what the rule saw*. `same_recording` hops resolve to the shared
    `track_index` and list only that track's credits; everything else lists the
    release-scope credits that connect the two artists.
    """
    release_id = int(hop["release_id"])
    artist_a_id, artist_b_id = int(hop["artist_a_id"]), int(hop["artist_b_id"])
    release, rows = lookup(release_id, {artist_a_id, artist_b_id})

    tracks_a = {
        r["track_index"]
        for r in rows
        if r["artist_id"] == artist_a_id and r.get("track_index") is not None
    }
    tracks_b = {
        r["track_index"]
        for r in rows
        if r["artist_id"] == artist_b_id and r.get("track_index") is not None
    }
    shared = sorted(tracks_a & tracks_b)

    is_same_recording = "same_recording" in hop.get("quality_flags", [])
    if shared:
        connection, track_index = "same_recording", shared[0]
        evidence = [r for r in rows if r.get("track_index") == track_index]
    elif is_same_recording:
        # The graph's single-billed fallback supplies a release artist as the
        # implicit performer when Discogs only records the guest at track
        # scope. The hop is still one recording; show that guest track rather
        # than mislabelling it as an album-wide credit.
        track_rows = [r for r in rows if r.get("track_index") is not None]
        track_index = min((r["track_index"] for r in track_rows), default=None)
        connection = "same_recording"
        evidence = [r for r in track_rows if r.get("track_index") == track_index]
    else:
        connection, track_index = "release_scope_credit", None
        evidence = [r for r in rows if r.get("track_index") is None] or rows

    def _credit(row: dict[str, Any]) -> dict[str, Any]:
        role = row.get("role_text")
        return {
            "artist_id": int(row["artist_id"]),
            "artist": str(row.get("name") or f"artist {row['artist_id']}"),
            "credit_scope": row.get("credit_scope"),
            # The original Discogs role text, never normalized -- the standing
            # evidence rule. `None` is a main-artist credit.
            "role": role,
            # Did THIS credit justify the edge, or does it merely sit on the
            # same record? A `Written-By` or `Remix` on the shared track is
            # evidence of nothing (ADR 0035) -- showing it without saying so
            # would let a curator credit the graph with a link it never made.
            "justifies_edge": not edge_ineligible_role(role),
        }

    return {
        "release_id": release_id,
        "release_url": f"https://www.discogs.com/release/{release_id}",
        "release_title": (release or {}).get("title"),
        "release_year": _year((release or {}).get("released")),
        "artist_a_id": artist_a_id,
        "artist_b_id": artist_b_id,
        "artist_a": _display_name(rows, artist_a_id),
        "artist_b": _display_name(rows, artist_b_id),
        "connection": connection,
        "track_position": next(
            (r.get("track_position") for r in evidence if r.get("track_position")), None
        ),
        "track_title": next((r.get("track_title") for r in evidence if r.get("track_title")), None),
        "credits": sorted(
            (_credit(r) for r in evidence),
            key=lambda c: (c["artist_id"], str(c["credit_scope"]), str(c["role"])),
        ),
        "quality_flags": hop.get("quality_flags", []),
    }


def _intermediaries(pair: dict[str, Any], explained: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The artists a multi-hop path routes *through* -- "the artists in common".
    A one-hop pair has none: the two album artists share a recording directly."""
    endpoints = {int(pair["artist_a_id"]), int(pair["artist_b_id"])}
    seen: dict[int, str] = {}
    for hop in explained:
        for artist_id, name in (
            (hop["artist_a_id"], hop["artist_a"]),
            (hop["artist_b_id"], hop["artist_b"]),
        ):
            if artist_id not in endpoints:
                seen.setdefault(int(artist_id), str(name))
    return [{"artist_id": a, "name": n} for a, n in seen.items()]


def _pair_score(
    pair: dict[str, Any], release_counts: Counter[str], endpoint_counts: Counter[str]
) -> tuple[int, list[str]]:
    score = {"easy": 30, "medium": 20, "hard": 8, "very_hard": 0}.get(pair["difficulty"], 0)
    reasons = [f"{pair['difficulty']} path"]
    hops = pair.get("hops", [])
    flags = {flag for hop in hops for flag in hop.get("quality_flags", [])}
    # Scope beats role. Before ADR 0035 a hop's `performer_credit` flag meant
    # only "role_text was not a known non-performer token", which every
    # compilation track artist satisfies -- so the top-ranked suggestion of the
    # 2026-07-09 run was Pink Floyd and Prince, on different sides of a Greek
    # promo compilation. `credit_edges` no longer builds that edge at all, and
    # ranking now leads with whether every hop is same-recording evidence.
    if hops and all("same_recording" in hop.get("quality_flags", []) for hop in hops):
        score += 35
        reasons.append("same-recording evidence throughout")
    elif "same_recording" in flags:
        score += 15
        reasons.append("same-recording evidence on some hops")
    if "performer_credit" in flags:
        score += 10
        reasons.append("performer-caliber evidence")
    if "co_billed_release_artists" in flags:
        score += 10
        reasons.append("co-billed release evidence")
    if "non_performer_only" in flags:
        # A studio-only link (producer/engineer/mixer). Real, but weaker than a
        # performance -- and no longer the container artifact it used to flag,
        # so the old -45 would now punish e.g. Nirvana <-> Butch Vig.
        score -= 15
        reasons.append("studio-credit-only evidence")
    if pair.get("warnings"):
        score -= 35
        reasons.append("scorer warning")
    repeated_releases = sum(
        max(0, release_counts[str(hop["release_id"])] - 1) for hop in pair.get("hops", [])
    )
    if repeated_releases:
        score -= min(20, repeated_releases * 3)
        reasons.append("repeated intermediary release")
    endpoint_repetition = sum(
        max(0, endpoint_counts[album_id] - 1)
        for album_id in (pair["album_a_id"], pair["album_b_id"])
    )
    if endpoint_repetition:
        score -= min(24, endpoint_repetition * 2)
        reasons.append("repeated endpoint; prefer a more diverse shortlist")
    return score, reasons


def _cover_map(resolved: dict[str, Any], cache_dir: Path | None) -> dict[str, str]:
    if cache_dir is None:
        return {}
    covers: dict[str, str] = {}
    for album in resolved.get("resolved", []):
        cache_path = cache_dir / f"{album.get('release_id')}.json"
        if not cache_path.is_file():
            continue
        try:
            payload = json.loads(cache_path.read_text())
            images = payload.get("images") or []
            primary = sorted(images, key=lambda image: 0 if image.get("type") == "primary" else 1)[
                0
            ]
            if primary.get("uri150"):
                covers[f"master-{album['master_id']}"] = str(primary["uri150"])
        except (IndexError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return covers


def build_editorial_packet(
    resolved: dict[str, Any],
    connectivity: dict[str, Any],
    cache_dir: Path | None = None,
    evidence_lookup: EvidenceLookup | None = None,
) -> dict[str, Any]:
    """Rank found pairs as suggestions; no result is an approval.

    With `evidence_lookup`, every hop is additionally explained (release title,
    the shared recording, and each artist's credited role) so a curator can
    judge a connection without opening Discogs. Without it the packet keeps its
    older, id-only `evidence_hops` shape.
    """
    albums = _album_map(resolved)
    covers = _cover_map(resolved, cache_dir)
    pairs = [pair for pair in connectivity.get("pairs", []) if pair.get("status") == "found"]
    release_counts = Counter(
        str(hop["release_id"])
        for pair in pairs
        for hop in pair.get("hops", [])
        if "release_id" in hop
    )
    endpoint_counts = Counter(
        album_id for pair in pairs for album_id in (pair["album_a_id"], pair["album_b_id"])
    )
    # One lookup per distinct evidence release, not per hop: the same release
    # commonly evidences many pairs.
    explained_cache: dict[tuple[int, int, int], dict[str, Any]] = {}

    def _evidence_hops(pair: dict[str, Any]) -> list[dict[str, Any]]:
        hops = pair.get("hops", [])
        if evidence_lookup is None:
            return [
                {
                    "release_id": hop["release_id"],
                    "release_url": f"https://www.discogs.com/release/{hop['release_id']}",
                    "quality_flags": hop.get("quality_flags", []),
                }
                for hop in hops
            ]
        explained = []
        for hop in hops:
            cache_key = (int(hop["release_id"]), int(hop["artist_a_id"]), int(hop["artist_b_id"]))
            if cache_key not in explained_cache:
                explained_cache[cache_key] = explain_hop(hop, evidence_lookup)
            explained.append(explained_cache[cache_key])
        return explained

    ranked: list[dict[str, Any]] = []
    for pair in pairs:
        score, reasons = _pair_score(pair, release_counts, endpoint_counts)
        evidence_hops = _evidence_hops(pair)
        ranked.append(
            {
                "album_a_id": pair["album_a_id"],
                "album_b_id": pair["album_b_id"],
                "artist_a_id": pair.get("artist_a_id"),
                "artist_b_id": pair.get("artist_b_id"),
                "artist_a": albums.get(pair["album_a_id"], {}).get("artist_name"),
                "artist_b": albums.get(pair["album_b_id"], {}).get("artist_name"),
                "title_a": albums.get(pair["album_a_id"], {}).get("title"),
                "title_b": albums.get(pair["album_b_id"], {}).get("title"),
                "year_a": albums.get(pair["album_a_id"], {}).get("year"),
                "year_b": albums.get(pair["album_b_id"], {}).get("year"),
                "cover_image_a": covers.get(pair["album_a_id"]),
                "cover_image_b": covers.get(pair["album_b_id"]),
                "difficulty": pair["difficulty"],
                "hop_count": pair["hop_count"],
                "hops": pair.get("hops", []),
                "evidence_hops": evidence_hops,
                "intermediaries": (
                    _intermediaries(pair, evidence_hops)
                    if evidence_lookup is not None and "artist_a_id" in pair
                    else []
                ),
                "warnings": pair.get("warnings", []),
                "review_required": bool(pair.get("warnings")),
                "editorial_score": score,
                "score_reasons": reasons,
            }
        )
    ranked.sort(key=lambda item: (-item["editorial_score"], item["album_a_id"], item["album_b_id"]))
    suggested: list[dict[str, Any]] = []
    suggested_endpoint_counts: Counter[str] = Counter()
    for item in ranked:
        endpoints = (item["album_a_id"], item["album_b_id"])
        if any(suggested_endpoint_counts[endpoint] >= 2 for endpoint in endpoints):
            continue
        suggested.append(item)
        suggested_endpoint_counts.update(endpoints)
        if len(suggested) == 20:
            break
    if len(suggested) < min(20, len(ranked)):
        selected = {id(item) for item in suggested}
        suggested.extend(item for item in ranked if id(item) not in selected)
        suggested = suggested[:20]
    return {
        "schema_version": 1,
        "status": "suggestions-only",
        "source": connectivity.get("source", {}),
        "scorer_version": connectivity.get("scorer_version"),
        "pair_count": len(ranked),
        "suggested_pairs": suggested,
        "ranked_pairs": ranked,
        "review_required_count": sum(item["review_required"] for item in ranked),
    }


def write_editorial_packet(
    packet: dict[str, Any], output_json: Path, output_markdown: Path
) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Local cohort editorial review packet",
        "",
        "This is a suggestions-only shortlist. It does not approve, promote, or publish pairs.",
        "",
        f"- Scored pairs: {packet['pair_count']}",
        f"- Suggested pairs: {len(packet['suggested_pairs'])}",
        f"- Pairs requiring explicit review: {packet['review_required_count']}",
        "",
        "## Suggested pairs",
        "",
        "| Score | Pair | Difficulty | Review | Reasons |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for item in packet["suggested_pairs"]:
        pair = f"{item['artist_a']} — {item['title_a']} / {item['artist_b']} — {item['title_b']}"
        review = "REVIEW" if item["review_required"] else "clean"
        lines.append(
            f"| {item['editorial_score']} | {pair} | {item['difficulty']} | {review} | "
            f"{'; '.join(item['score_reasons'])} |"
        )
    output_markdown.write_text("\n".join(lines) + "\n")
