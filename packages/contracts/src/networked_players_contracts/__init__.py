"""Dependency-free validators for public Networked Players artifacts."""

from .cohort import (
    CONNECTIVITY_SCHEMA_VERSION,
    PLAYABLE_COHORT_SCHEMA_VERSION,
    connectivity_failures,
    playable_cohort_failures,
)

__all__ = [
    "CONNECTIVITY_SCHEMA_VERSION",
    "PLAYABLE_COHORT_SCHEMA_VERSION",
    "connectivity_failures",
    "playable_cohort_failures",
]

__version__ = "0.1.0"
