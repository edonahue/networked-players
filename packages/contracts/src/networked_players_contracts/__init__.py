"""Dependency-free validators for public Networked Players artifacts."""

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
    "CONNECTION_ROUNDS_SCHEMA_VERSION",
    "CONNECTIVITY_SCHEMA_VERSION",
    "PLAYABLE_COHORT_SCHEMA_VERSION",
    "ROUNDS_SCHEMA_VERSION",
    "connection_rounds_failures",
    "connectivity_failures",
    "playable_cohort_failures",
    "rounds_failures",
]

__version__ = "0.1.0"
