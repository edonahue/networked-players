"""Canonical JSON serialization and content hashing, shared verbatim between
generation-time code (`networked_players_graph_core`) and the dependency-free
validators in this package -- not a structurally-mirrored duplicate, an
actual shared import, so the two can never silently drift on what "the same
content" means (see ADR 0043's corrective-slice-4.6 addendum).

Deterministic and insensitive to insignificant JSON formatting: key order,
whitespace, and which serializer happened to write a file to disk never
change the result -- only the actual value tree does. Both Python's
`json.dumps` here and the TypeScript port in `apps/web/src/game/canonical.ts`
must produce byte-identical canonical strings for the same value (sorted
keys, no extra whitespace, non-ASCII characters left unescaped rather than
`\\uXXXX`-encoded) so a content hash computed in either language agrees.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """A deterministic JSON string: keys sorted at every nesting level, no
    insignificant whitespace, non-ASCII left as literal UTF-8 (matching
    JavaScript's `JSON.stringify` default) so this agrees byte-for-byte with
    the TypeScript port for the same value."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any, *, length: int = 16) -> str:
    """A truncated sha256 hex digest of `value`'s canonical JSON form, hashed
    as UTF-8 bytes (matching `TextEncoder().encode(...)` in the TypeScript
    port)."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return digest[:length]


def stable_id_digest(*parts: str, length: int = 10) -> str:
    """A truncated sha256 hex digest of pipe-joined string `parts` -- the
    primitive behind a round's own stable, content-derived id
    (`connection_rounds.py::_stable_id`). Shared here so a dependency-free
    validator can recompute a round's id from its own published semantic
    fields (endpoints + accepted answers) and prove self-consistency without
    needing the original Discogs credit graph."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:length]
