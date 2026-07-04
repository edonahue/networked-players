"""Optional cover-art enrichment for a challenge.v2 artifact via the Discogs API.

Rate-limited, only for matched albums' main releases -- the same posture as
ADR 0012's demo-challenge API use. Cover art is presentational only, never
load-bearing evidence (docs/DATA_AND_RIGHTS.md); an artifact with every
cover_image left null is still a complete, valid challenge.
"""

from __future__ import annotations

from typing import Any

from .api_client import ApiClient, ReleaseCache, fetch_releases


def cover_image_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The best cover image from a raw /releases/{id} API payload, or None."""
    raw = payload.get("images") or []
    ordered = sorted(raw, key=lambda img: 0 if img.get("type") == "primary" else 1)
    for image in ordered:
        uri, uri150 = image.get("uri"), image.get("uri150")
        if uri and uri150:
            return {
                "uri": uri,
                "uri150": uri150,
                "width": int(image.get("width") or 0),
                "height": int(image.get("height") or 0),
            }
    return None


def enrich_challenge_albums(
    artifact: dict[str, Any],
    *,
    client: ApiClient,
    cache: ReleaseCache,
) -> int:
    """Fetch each album's main release and set cover_image in place. Returns the enriched count."""
    release_ids = [album["main_release_id"] for album in artifact["albums"]]
    raw = fetch_releases(release_ids, client=client, cache=cache)

    enriched = 0
    for album in artifact["albums"]:
        payload = raw.get(album["main_release_id"])
        if payload is None:
            continue
        cover_image = cover_image_from_payload(payload)
        if cover_image is not None:
            album["cover_image"] = cover_image
            enriched += 1
    return enriched
