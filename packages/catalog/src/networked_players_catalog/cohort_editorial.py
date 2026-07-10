"""Transparent, local-only editorial ranking for a scored cohort."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _album_map(resolved: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"master-{item['master_id']}": item for item in resolved.get("resolved", [])}


def _pair_score(
    pair: dict[str, Any], release_counts: Counter[str], endpoint_counts: Counter[str]
) -> tuple[int, list[str]]:
    score = {"easy": 30, "medium": 20, "hard": 8, "very_hard": 0}.get(pair["difficulty"], 0)
    reasons = [f"{pair['difficulty']} path"]
    flags = {flag for hop in pair.get("hops", []) for flag in hop.get("quality_flags", [])}
    if "performer_credit" in flags:
        score += 35
        reasons.append("performer-caliber evidence")
    if "co_billed_release_artists" in flags:
        score += 20
        reasons.append("co-billed release evidence")
    if "non_performer_only" in flags:
        score -= 45
        reasons.append("non-performer-only evidence")
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
    resolved: dict[str, Any], connectivity: dict[str, Any], cache_dir: Path | None = None
) -> dict[str, Any]:
    """Rank found pairs as suggestions; no result is an approval."""
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
    ranked: list[dict[str, Any]] = []
    for pair in pairs:
        score, reasons = _pair_score(pair, release_counts, endpoint_counts)
        ranked.append(
            {
                "album_a_id": pair["album_a_id"],
                "album_b_id": pair["album_b_id"],
                "artist_a": albums.get(pair["album_a_id"], {}).get("artist_name"),
                "artist_b": albums.get(pair["album_b_id"], {}).get("artist_name"),
                "title_a": albums.get(pair["album_a_id"], {}).get("title"),
                "title_b": albums.get(pair["album_b_id"], {}).get("title"),
                "cover_image_a": covers.get(pair["album_a_id"]),
                "cover_image_b": covers.get(pair["album_b_id"]),
                "difficulty": pair["difficulty"],
                "hop_count": pair["hop_count"],
                "hops": pair.get("hops", []),
                "evidence_hops": [
                    {
                        "release_id": hop["release_id"],
                        "release_url": f"https://www.discogs.com/release/{hop['release_id']}",
                        "quality_flags": hop.get("quality_flags", []),
                    }
                    for hop in pair.get("hops", [])
                ],
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
