from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_research.request import (
    DEFAULT_HOP_TIER,
    ResearchRequestError,
    load_request,
    parse_request,
)


def _valid_payload() -> dict:
    return {
        "topic": "Jamiroquai",
        "seeds": {"artists": ["Jamiroquai"]},
        "questions": ["How did personnel change?"],
        "scope": {"hop_tier": 1},
        "analyses": ["personnel_timeline"],
    }


def test_parses_a_valid_request() -> None:
    request = parse_request(_valid_payload())
    assert request.topic == "Jamiroquai"
    assert request.seed_artist_names == ("Jamiroquai",)
    assert request.hop_tier == 1
    assert request.analyses == ("personnel_timeline",)


def test_defaults_hop_tier_and_analyses_when_omitted() -> None:
    payload = _valid_payload()
    del payload["scope"]
    del payload["analyses"]
    request = parse_request(payload)
    assert request.hop_tier == DEFAULT_HOP_TIER
    assert set(request.analyses) == {
        "personnel_timeline",
        "role_distribution",
        "contributor_network",
        "community_detection",
        "bridge_analysis",
        "temporal_comparison",
    }


def test_topic_slug_is_filesystem_safe() -> None:
    request = parse_request({**_valid_payload(), "topic": "  Jamiroquai! & Friends  "})
    assert request.topic_slug() == "jamiroquai-friends"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("topic"),
        lambda p: p.__setitem__("topic", ""),
        lambda p: p.pop("seeds"),
        lambda p: p.__setitem__("seeds", {"artists": []}),
        lambda p: p.__setitem__("scope", {"hop_tier": 0}),
        lambda p: p.__setitem__("analyses", ["not_a_real_analysis"]),
    ],
)
def test_invalid_requests_fail_loud(mutate) -> None:
    payload = _valid_payload()
    mutate(payload)
    with pytest.raises(ResearchRequestError):
        parse_request(payload)


def test_load_request_reads_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_valid_payload()))
    request = load_request(path)
    assert request.topic == "Jamiroquai"
