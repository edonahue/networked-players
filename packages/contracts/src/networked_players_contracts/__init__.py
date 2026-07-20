"""Dependency-free validators for public Networked Players artifacts."""

from .cohort import (
    CONNECTIVITY_SCHEMA_VERSION,
    PLAYABLE_COHORT_SCHEMA_VERSION,
    connectivity_failures,
    playable_cohort_failures,
)
from .rounds import ROUNDS_SCHEMA_VERSION, rounds_failures

__all__ = [
    "CONNECTIVITY_SCHEMA_VERSION",
    "PLAYABLE_COHORT_SCHEMA_VERSION",
    "ROUNDS_SCHEMA_VERSION",
    "connectivity_failures",
    "playable_cohort_failures",
    "rounds_failures",
]

__version__ = "0.1.0"
