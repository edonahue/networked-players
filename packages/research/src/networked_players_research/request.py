"""The Research Run request contract: a small, human-readable JSON file
(deliberately not YAML -- no new dependency was justified for a schema this
flat and small; see ADR 0054) describing what a research run should do.
Never executed as code -- `questions` is free text carried through into the
eventual report, `analyses` is a fixed, reviewable set of names, not a
query language.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The complete, reviewable set of analyses a request may ask for (Slice D
# implements each). An unrecognized name is a hard error at load time --
# never silently ignored, since a typo'd analysis name should not silently
# produce a report missing a section the operator thought they asked for.
ANALYSIS_NAMES = frozenset(
    {
        "personnel_timeline",
        "role_distribution",
        "contributor_network",
        "community_detection",
        "bridge_analysis",
        "temporal_comparison",
    }
)

DEFAULT_HOP_TIER = 1


class ResearchRequestError(ValueError):
    """Raised for a malformed or invalid request.json -- never guessed past."""


@dataclass(frozen=True)
class ResearchRequest:
    topic: str
    seed_artist_names: tuple[str, ...]
    questions: tuple[str, ...]
    hop_tier: int
    analyses: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False)

    def topic_slug(self) -> str:
        """A filesystem-safe slug for `local/research/<slug>/` -- lowercase,
        spaces/punctuation collapsed to a single hyphen, never empty."""
        slug = "".join(c.lower() if c.isalnum() else "-" for c in self.topic)
        while "--" in slug:
            slug = slug.replace("--", "-")
        slug = slug.strip("-")
        if not slug:
            raise ResearchRequestError(f"topic {self.topic!r} has no usable slug characters")
        return slug


def parse_request(payload: dict[str, Any]) -> ResearchRequest:
    """Validate and parse an already-loaded request payload. Fails loud on
    anything malformed rather than defaulting past it -- a request is a
    human-authored file, and a silently-ignored typo would produce a
    confusingly incomplete run."""
    if not isinstance(payload, dict):
        raise ResearchRequestError("request must be a JSON object")

    topic = payload.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ResearchRequestError("request.topic must be a non-empty string")

    seeds = payload.get("seeds")
    if not isinstance(seeds, dict):
        raise ResearchRequestError("request.seeds must be an object")
    seed_artists = seeds.get("artists")
    if (
        not isinstance(seed_artists, list)
        or not seed_artists
        or not all(isinstance(a, str) and a.strip() for a in seed_artists)
    ):
        raise ResearchRequestError("request.seeds.artists must be a non-empty list of strings")

    questions = payload.get("questions", [])
    if not isinstance(questions, list) or not all(isinstance(q, str) for q in questions):
        raise ResearchRequestError("request.questions must be a list of strings")

    scope = payload.get("scope", {})
    if not isinstance(scope, dict):
        raise ResearchRequestError("request.scope must be an object")
    hop_tier = scope.get("hop_tier", DEFAULT_HOP_TIER)
    if not isinstance(hop_tier, int) or hop_tier < 1:
        raise ResearchRequestError("request.scope.hop_tier must be a positive integer")

    analyses = payload.get("analyses", sorted(ANALYSIS_NAMES))
    if not isinstance(analyses, list) or not all(isinstance(a, str) for a in analyses):
        raise ResearchRequestError("request.analyses must be a list of strings")
    unknown = sorted(set(analyses) - ANALYSIS_NAMES)
    if unknown:
        raise ResearchRequestError(
            f"request.analyses has unrecognized names {unknown}; valid names are "
            f"{sorted(ANALYSIS_NAMES)}"
        )

    return ResearchRequest(
        topic=topic,
        seed_artist_names=tuple(seed_artists),
        questions=tuple(questions),
        hop_tier=hop_tier,
        analyses=tuple(analyses),
        raw=payload,
    )


def load_request(path: Path) -> ResearchRequest:
    return parse_request(json.loads(path.read_text()))
