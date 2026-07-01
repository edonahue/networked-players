from __future__ import annotations

import json
from pathlib import Path

from networked_players_catalog.discogs.demo_challenge import (
    build_adjacency,
    build_challenge,
    curate_paths,
    find_candidate_paths,
    parse_api_release,
    top_connected_artists,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "samples" / "discogs-api-release-sample.json"
)
SNAPSHOT_DATE = "20260701"


def _load_raw_releases() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())


def _parsed_releases_by_id() -> dict[int, dict]:
    return {
        payload["id"]: parse_api_release(payload, snapshot_date=SNAPSHOT_DATE)
        for payload in _load_raw_releases()
    }


def test_parse_api_release_falls_back_to_year_and_synthesized_url() -> None:
    releases_by_id = _parsed_releases_by_id()
    release = releases_by_id[5016]

    assert release["released"] == "1993"
    assert release["country"] is None
    assert release["master_id"] is None
    assert release["data_quality"] is None
    assert release["images"] == []
    assert release["source_url"] == "https://www.discogs.com/release/5016"


def test_parse_api_release_prefers_uri_when_present() -> None:
    releases_by_id = _parsed_releases_by_id()
    release = releases_by_id[5001]

    assert release["source_url"] == "https://www.discogs.com/release/5001-First-Light"
    assert len(release["images"]) == 2
    assert release["images"][0]["uri"].startswith("https://img.discogs.com/")


def test_release_level_tracks_text_credit_stays_release_credit_scope() -> None:
    releases_by_id = _parsed_releases_by_id()
    release = releases_by_id[5015]

    extra = next(c for c in release["credits"] if c["artist_id"] == 110)
    assert extra["credit_scope"] == "release_credit"
    assert extra["credited_tracks_text"] == "1-2"
    assert extra["track_index"] is None


def test_nested_track_credits_get_track_scope_with_index() -> None:
    releases_by_id = _parsed_releases_by_id()
    release = releases_by_id[5011]

    track_artist = next(c for c in release["credits"] if c["artist_id"] == 108)
    assert track_artist["credit_scope"] == "track_artist"
    assert track_artist["track_index"] == 0
    assert track_artist["track_position"] == "1"
    assert track_artist["anv"] == "T. Field"

    track_credit = next(c for c in release["credits"] if c["artist_id"] == 109)
    assert track_credit["credit_scope"] == "track_credit"
    assert track_credit["track_index"] == 0


def test_unlinked_artist_is_not_playable() -> None:
    releases_by_id = _parsed_releases_by_id()
    release = releases_by_id[5001]

    unlinked = next(c for c in release["credits"] if c["name"] == "Unknown Artist")
    assert unlinked["artist_id"] is None
    assert unlinked["is_linked"] is False
    assert unlinked["playable_identity"] is False


def test_various_placeholder_artist_is_not_playable() -> None:
    various_artist = {
        "id": 194,
        "name": "Various",
        "anv": "",
        "join": "",
        "role": "",
        "tracks": "",
    }
    payload = {
        "id": 6001,
        "title": "Compilation",
        "artists": [various_artist],
        "extraartists": [],
        "tracklist": [],
        "images": [],
    }
    release = parse_api_release(payload, snapshot_date=SNAPSHOT_DATE)

    various = next(c for c in release["credits"] if c["name"] == "Various")
    assert various["artist_id"] is None
    assert various["is_linked"] is False
    assert various["playable_identity"] is False


def test_build_adjacency_finds_expected_pairs() -> None:
    releases_by_id = _parsed_releases_by_id()
    adjacency = build_adjacency(list(releases_by_id.values()))

    # Adjacency connects every *linked* credit on a release, regardless of scope --
    # 101 co-appears with 108/109 (track credits) and 110 (release_credit) via
    # releases 5011 and 5015, not just its fellow release_artist entries.
    assert set(adjacency[101]) == {102, 103, 104, 105, 108, 109, 110}
    # The unlinked "Unknown Artist" (id 0 -> None) never appears as a graph node.
    assert None not in adjacency


def test_curate_paths_has_no_duplicate_endpoint_pairs() -> None:
    releases_by_id = _parsed_releases_by_id()
    adjacency = build_adjacency(list(releases_by_id.values()))
    seeds = top_connected_artists(adjacency, count=5)
    candidates = find_candidate_paths(adjacency, releases_by_id, seed_artist_ids=seeds)
    curated = curate_paths(candidates, limit=8)

    pairs = [tuple(sorted((c.from_artist_id, c.to_artist_id))) for c in curated]
    assert len(pairs) == len(set(pairs))


def test_build_challenge_publishes_a_curated_subset_not_everything() -> None:
    releases_by_id = _parsed_releases_by_id()
    challenge = build_challenge(
        releases_by_id,
        snapshot_date=SNAPSHOT_DATE,
        generated_by="test-suite",
        max_paths=4,
        seed_count=3,
    )

    assert len(challenge["releases"]) < len(releases_by_id)
    assert len(challenge["paths"]) <= 4
    assert challenge["provenance"]["snapshot_date"] == SNAPSHOT_DATE
    assert "216" not in json.dumps(challenge)
