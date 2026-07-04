from __future__ import annotations

import json
from pathlib import Path

from networked_players_graph_core.challenge import build_challenge_v2, validate_challenge
from networked_players_graph_core.graph import CreditGraph

ALBUMS = [
    {"artist": "Alice", "title": "First Light"},
    {"artist": "Cara", "title": "Third Wave"},
    {"artist": "Eve", "title": "Sixth Sense"},
]

# Matches challenge.py's own leak scan. "seed" is deliberately not a forbidden
# substring -- the honest provenance note legitimately mentions "the private
# collection seed" in prose; what must never appear is a `seed` *key* (checked
# separately below), a real path, or a credential.
FORBIDDEN_SUBSTRINGS = ("/home/", "data/private", "local/", "DISCOGS_TOKEN", ".ssh")


def test_artifact_contains_no_private_or_seed_material(dataset_root: Path) -> None:
    with CreditGraph.open(dataset_root) as graph:
        artifact, _ = build_challenge_v2(
            graph, ALBUMS, snapshot_date="20260601", generated_by="test-suite"
        )

    validate_challenge(artifact)  # runs the same leak scan build-challenge-from-dump relies on
    serialized = json.dumps(artifact)
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in serialized

    assert set(artifact.keys()) == {
        "schema_version",
        "provenance",
        "albums",
        "artists",
        "paths",
        "releases",
    }
    assert "seed" not in artifact["provenance"]
