from __future__ import annotations

import json
from pathlib import Path

from networked_players_catalog.cohort_editorial import (
    build_editorial_packet,
    explain_hop,
    write_editorial_packet,
)


def _inputs() -> tuple[dict, dict]:
    resolved = {
        "resolved": [
            {"master_id": 1, "release_id": 11, "artist_name": "Alice", "title": "One"},
            {"master_id": 2, "release_id": 12, "artist_name": "Bob", "title": "Two"},
            {"master_id": 3, "release_id": 13, "artist_name": "Cara", "title": "Three"},
        ]
    }
    connectivity = {
        "scorer_version": 3,
        "source": {"source_url": "https://example.invalid/source"},
        "pairs": [
            {
                "album_a_id": "master-1",
                "album_b_id": "master-2",
                "difficulty": "easy",
                "hop_count": 1,
                "status": "found",
                "warnings": [],
                "hops": [{"release_id": 7, "quality_flags": ["performer_credit"]}],
            },
            {
                "album_a_id": "master-2",
                "album_b_id": "master-3",
                "difficulty": "easy",
                "hop_count": 1,
                "status": "found",
                "warnings": ["check this"],
                "hops": [{"release_id": 8, "quality_flags": ["non_performer_only"]}],
            },
        ],
    }
    return resolved, connectivity


def test_editorial_packet_is_suggestions_only_and_flags_warnings() -> None:
    packet = build_editorial_packet(*_inputs())
    assert packet["status"] == "suggestions-only"
    assert packet["suggested_pairs"][0]["album_a_id"] == "master-1"
    assert packet["review_required_count"] == 1
    assert packet["ranked_pairs"][0]["evidence_hops"][0]["release_url"].endswith("/7")


def test_editorial_packet_writes_local_json_and_markdown(tmp_path: Path) -> None:
    packet = build_editorial_packet(*_inputs())
    output_json = tmp_path / "packet.json"
    output_markdown = tmp_path / "packet.md"
    write_editorial_packet(packet, output_json, output_markdown)
    assert json.loads(output_json.read_text())["status"] == "suggestions-only"
    assert "does not approve" in output_markdown.read_text()


def test_editorial_packet_uses_cached_discogs_thumbnail(tmp_path: Path) -> None:
    (tmp_path / "11.json").write_text(
        json.dumps({"images": [{"type": "primary", "uri150": "https://img.example/11.jpg"}]})
    )
    packet = build_editorial_packet(*_inputs(), cache_dir=tmp_path)
    assert packet["ranked_pairs"][0]["cover_image_a"] == "https://img.example/11.jpg"


# --- hop explanation: the evidence a curator judges a connection on ---


def _row(artist_id, name, scope, role=None, track_index=None, position=None, title=None):
    return {
        "artist_id": artist_id,
        "name": name,
        "credit_scope": scope,
        "role_text": role,
        "track_index": track_index,
        "track_position": position,
        "track_title": title,
    }


def test_explain_hop_resolves_a_shared_recording_and_its_roles() -> None:
    """Nas and Lauryn Hill share track 13 of a compilation; only that track's
    credits are evidence, and the original Discogs role text is preserved."""
    release = {"title": "Serious Hits '96", "released": "1996-09-00"}
    rows = [
        _row(50997, "Nas", "track_artist", None, 13, "13", "If I Ruled The World"),
        _row(42627, "Lauryn Hill", "track_credit", "Vocals", 13, "13", "If I Ruled The World"),
        # A different track on the same release: never evidence for this hop.
        _row(50997, "Nas", "track_artist", None, 4, "4", "Some Other Song"),
    ]
    hop = {
        "release_id": 726564,
        "artist_a_id": 50997,
        "artist_b_id": 42627,
        "quality_flags": ["performer_credit", "same_recording"],
    }
    explained = explain_hop(hop, lambda _rid, _ids: (release, rows))

    assert explained["connection"] == "same_recording"
    assert explained["release_title"] == "Serious Hits '96"
    assert explained["release_year"] == "1996"
    assert explained["track_title"] == "If I Ruled The World"
    assert explained["artist_a"] == "Nas" and explained["artist_b"] == "Lauryn Hill"
    assert explained["release_url"] == "https://www.discogs.com/release/726564"
    assert explained["credits"] == [
        {
            "artist_id": 42627,
            "artist": "Lauryn Hill",
            "credit_scope": "track_credit",
            "role": "Vocals",
            "justifies_edge": True,
        },
        {
            "artist_id": 50997,
            "artist": "Nas",
            "credit_scope": "track_artist",
            "role": None,
            "justifies_edge": True,
        },
    ]


def test_explain_hop_falls_back_to_release_scope_credits() -> None:
    """Nirvana and Butch Vig share no track: he is credited to the whole album."""
    release = {"title": "Nevermind", "released": "1991"}
    rows = [
        _row(125246, "Nirvana", "release_artist"),
        _row(42640, "Butch Vig", "release_credit", "Producer, Engineer"),
        _row(125246, "Nirvana", "track_artist", None, 0, "1", "Smells Like Teen Spirit"),
    ]
    hop = {
        "release_id": 1813006,
        "artist_a_id": 125246,
        "artist_b_id": 42640,
        "quality_flags": ["performer_credit", "release_scope_credit"],
    }
    explained = explain_hop(hop, lambda _rid, _ids: (release, rows))

    assert explained["connection"] == "release_scope_credit"
    assert explained["track_title"] is None
    assert {c["role"] for c in explained["credits"]} == {None, "Producer, Engineer"}


def test_explain_hop_shows_the_guest_track_for_billed_artist_fallback() -> None:
    """A billed artist may be implicit when only the guest has a track row."""
    release = {"title": "Taken For A Fool", "released": "2011"}
    rows = [
        _row(55980, "The Strokes", "release_artist"),
        _row(
            55029,
            "Elvis Costello",
            "track_credit",
            "Featuring",
            1,
            "B",
            "Taken For A Fool (Live From Madison Square Garden)",
        ),
    ]
    hop = {
        "release_id": 3056804,
        "artist_a_id": 55980,
        "artist_b_id": 55029,
        "quality_flags": ["performer_credit", "same_recording"],
    }
    explained = explain_hop(hop, lambda _rid, _ids: (release, rows))

    assert explained["connection"] == "same_recording"
    assert explained["track_position"] == "B"
    assert explained["track_title"] == "Taken For A Fool (Live From Madison Square Garden)"


def test_build_editorial_packet_explains_hops_and_names_intermediaries() -> None:
    resolved, connectivity = _inputs()
    two_hop = connectivity["pairs"][0]
    two_hop["artist_a_id"], two_hop["artist_b_id"] = 100, 300
    two_hop["hop_count"] = 2
    two_hop["hops"] = [
        {
            "release_id": 7,
            "artist_a_id": 100,
            "artist_b_id": 200,
            "quality_flags": ["performer_credit", "same_recording"],
        },
        {
            "release_id": 9,
            "artist_a_id": 200,
            "artist_b_id": 300,
            "quality_flags": ["performer_credit", "same_recording"],
        },
    ]
    connectivity["pairs"] = [two_hop]

    def lookup(release_id, artist_ids):
        names = {100: "Alice", 200: "Bridge Player", 300: "Cara"}
        return (
            {"title": f"Release {release_id}", "released": "2001"},
            [_row(a, names[a], "track_artist", None, 0, "1", "A Song") for a in sorted(artist_ids)],
        )

    packet = build_editorial_packet(resolved, connectivity, None, evidence_lookup=lookup)
    pair = packet["ranked_pairs"][0]

    # The artist in common -- what the path routes through, not its endpoints.
    assert pair["intermediaries"] == [{"artist_id": 200, "name": "Bridge Player"}]
    assert [h["release_title"] for h in pair["evidence_hops"]] == ["Release 7", "Release 9"]
    assert all(h["connection"] == "same_recording" for h in pair["evidence_hops"])


def test_build_editorial_packet_without_a_dataset_keeps_the_id_only_shape() -> None:
    packet = build_editorial_packet(*_inputs())
    hop = packet["ranked_pairs"][0]["evidence_hops"][0]
    assert set(hop) == {"release_id", "release_url", "quality_flags"}
    assert packet["ranked_pairs"][0]["intermediaries"] == []


def test_explain_hop_marks_credits_that_cannot_justify_an_edge() -> None:
    """A `Remix` or `Written-By` credit on the shared track is context, not
    evidence -- the curator must be able to tell them apart from the credit
    that actually built the edge."""
    release = {"title": "Culture Shock Volume Fifteen", "released": "2006"}
    rows = [
        _row(55980, "The Strokes", "track_artist", None, 0, "1", "Juicebox"),
        _row(900100, "A Remixer", "track_credit", "Remix", 0, "1", "Juicebox"),
        _row(900101, "A Songwriter", "track_credit", "Written-By", 0, "1", "Juicebox"),
        _row(59472, "Andy Wallace", "track_credit", "Mixed By", 0, "1", "Juicebox"),
    ]
    hop = {
        "release_id": 1,
        "artist_a_id": 55980,
        "artist_b_id": 59472,
        "quality_flags": ["performer_credit", "same_recording"],
    }
    explained = explain_hop(hop, lambda _rid, _ids: (release, rows))
    by_artist = {c["artist_id"]: c["justifies_edge"] for c in explained["credits"]}

    assert by_artist[55980] is True, "a main track artist justifies the edge"
    assert by_artist[59472] is True, "Mixed By is studio work on the session"
    assert by_artist[900100] is False, "Remix is a rework"
    assert by_artist[900101] is False, "Written-By is composition, not collaboration"
