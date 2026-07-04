from __future__ import annotations

from pathlib import Path

from networked_players_catalog.discogs.album_art import (
    cover_image_from_payload,
    enrich_challenge_albums,
)
from networked_players_catalog.discogs.api_client import ApiClient, ReleaseCache


def test_cover_image_from_payload_prefers_primary() -> None:
    payload = {
        "images": [
            {
                "type": "secondary",
                "uri": "https://img/s.jpg",
                "uri150": "https://img/s150.jpg",
                "width": 100,
                "height": 100,
            },
            {
                "type": "primary",
                "uri": "https://img/p.jpg",
                "uri150": "https://img/p150.jpg",
                "width": 500,
                "height": 500,
            },
        ]
    }
    image = cover_image_from_payload(payload)
    assert image == {
        "uri": "https://img/p.jpg",
        "uri150": "https://img/p150.jpg",
        "width": 500,
        "height": 500,
    }


def test_cover_image_from_payload_skips_entries_missing_uris() -> None:
    payload = {"images": [{"type": "primary", "width": 500, "height": 500}]}
    assert cover_image_from_payload(payload) is None


def test_cover_image_from_payload_absent_when_no_images() -> None:
    assert cover_image_from_payload({}) is None


def test_enrich_challenge_albums_uses_cache_and_never_touches_network(tmp_path: Path) -> None:
    cache = ReleaseCache(tmp_path / "cache")
    cache.put(
        501,
        {
            "id": 501,
            "images": [
                {
                    "type": "primary",
                    "uri": "https://img/a.jpg",
                    "uri150": "https://img/a150.jpg",
                    "width": 300,
                    "height": 300,
                }
            ],
        },
    )
    cache.put(502, {"id": 502, "images": []})

    # base_url points nowhere real -- a cache miss here would raise, proving the
    # cache hit path never calls the network.
    client = ApiClient(token="synthetic-test-token", base_url="http://127.0.0.1:1")
    artifact = {
        "albums": [
            {"main_release_id": 501, "cover_image": None},
            {"main_release_id": 502, "cover_image": None},
        ]
    }

    enriched = enrich_challenge_albums(artifact, client=client, cache=cache)

    assert enriched == 1
    assert artifact["albums"][0]["cover_image"] == {
        "uri": "https://img/a.jpg",
        "uri150": "https://img/a150.jpg",
        "width": 300,
        "height": 300,
    }
    assert artifact["albums"][1]["cover_image"] is None
