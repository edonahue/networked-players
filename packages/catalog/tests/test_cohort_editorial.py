from __future__ import annotations

import json
from pathlib import Path

from networked_players_catalog.cohort_editorial import (
    build_editorial_packet,
    write_editorial_packet,
)


def _inputs() -> tuple[dict, dict]:
    resolved = {
        "resolved": [
            {"master_id": 1, "artist_name": "Alice", "title": "One"},
            {"master_id": 2, "artist_name": "Bob", "title": "Two"},
            {"master_id": 3, "artist_name": "Cara", "title": "Three"},
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


def test_editorial_packet_writes_local_json_and_markdown(tmp_path: Path) -> None:
    packet = build_editorial_packet(*_inputs())
    output_json = tmp_path / "packet.json"
    output_markdown = tmp_path / "packet.md"
    write_editorial_packet(packet, output_json, output_markdown)
    assert json.loads(output_json.read_text())["status"] == "suggestions-only"
    assert "does not approve" in output_markdown.read_text()
