"""Dependency-free validators for public Networked Players artifacts."""

from .album_art import (
    ALBUM_ART_SCHEMA_VERSION,
    album_art_failures,
    album_art_version,
)
from .canonical import canonical_json, content_hash, stable_id_digest
from .cohort import (
    CONNECTIVITY_SCHEMA_VERSION,
    PLAYABLE_COHORT_SCHEMA_VERSION,
    connectivity_failures,
    playable_cohort_failures,
)
from .connection_rounds import (
    CONNECTION_ROUNDS_SCHEMA_VERSION,
    connection_rounds_failures,
)
from .rounds import ROUNDS_SCHEMA_VERSION, rounds_failures

__all__ = [
    "ALBUM_ART_SCHEMA_VERSION",
    "CONNECTION_ROUNDS_SCHEMA_VERSION",
    "CONNECTIVITY_SCHEMA_VERSION",
    "PLAYABLE_COHORT_SCHEMA_VERSION",
    "ROUNDS_SCHEMA_VERSION",
    "album_art_failures",
    "album_art_version",
    "canonical_json",
    "connection_rounds_failures",
    "connectivity_failures",
    "content_hash",
    "playable_cohort_failures",
    "rounds_failures",
    "stable_id_digest",
]

__version__ = "0.1.0"
