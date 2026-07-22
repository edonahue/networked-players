"""Optional cover-art enrichment via the Discogs API.

Rate-limited, only for matched albums' main releases -- the same posture as
ADR 0012's demo-challenge API use. Cover art is presentational only, never
load-bearing evidence (docs/DATA_AND_RIGHTS.md); an artifact with every
cover_image left null is still a complete, valid challenge, and the separately
versioned album-art registry (ADR 0044/0045) with every album absent is still
a valid registry (the frontend renders placeholders).

`build_album_art_registry` produces the public, presentation-only art
registry keyed by canonical album id -- deliberately NOT embedded in any
frozen game content, so refreshing art never changes a round fingerprint or
the daily manifest (see networked_players_contracts.album_art).
"""

from __future__ import annotations

from typing import Any

from networked_players_contracts.album_art import album_art_version

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


def build_album_art_registry(
    catalog: dict[str, Any],
    *,
    client: ApiClient,
    cache: ReleaseCache,
    generated_at: str,
    source: str,
    license_note: str,
) -> dict[str, Any]:
    """Build the public album-art registry from the canonical catalog.

    Fetches each album's `main_release_id` (cache-first, resumable) and keeps
    only albums whose main release actually carries a usable cover image --
    an album with no image is simply absent (the frontend renders a
    placeholder). Hotlink URLs only; no image bytes are ever downloaded or
    stored. Deterministic given the same catalog + cache + `generated_at`."""
    albums = catalog["albums"]
    release_ids = [int(album["main_release_id"]) for album in albums]
    raw = fetch_releases(release_ids, client=client, cache=cache)

    entries: list[dict[str, Any]] = []
    for album in sorted(albums, key=lambda a: str(a["id"])):
        payload = raw.get(int(album["main_release_id"]))
        if payload is None:
            continue
        cover = cover_image_from_payload(payload)
        if cover is None:
            continue
        entries.append(
            {
                "album_id": album["id"],
                "main_release_id": int(album["main_release_id"]),
                "uri150": cover["uri150"],
                "uri": cover["uri"],
                "width": int(cover.get("width") or 0),
                "height": int(cover.get("height") or 0),
            }
        )

    snapshot_date = str(catalog["snapshot_date"])
    return {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "art_version": album_art_version(entries, snapshot_date),
        "generated_at": generated_at,
        "source": source,
        "license": license_note,
        "albums": entries,
    }
