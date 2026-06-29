"""Discogs dump acquisition and normalization."""

from .manifest import DumpKind, SnapshotManifest, build_manifest
from .releases import ParsedRelease, iter_releases

__all__ = ["DumpKind", "ParsedRelease", "SnapshotManifest", "build_manifest", "iter_releases"]
