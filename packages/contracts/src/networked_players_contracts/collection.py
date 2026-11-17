"""Dependency-free validation for Collections (ADR 0074, Campaign Atlas S2).

A Collection is a reviewed, thematic *view over the published catalog*: its
records are catalog albums (`master-...` ids), its bridge players, optional
journey and optional playable pairs are all facts of the performer-only
pathfinding graph (`graph.v4.json`, ADR 0068). Contract notes:
`data/contracts/collection-v1.md` and `data/contracts/playable-cohort-v2.md`.

What this module does NOT do: decide, build or publish anything. It only
checks. The builder is `networked_players_catalog.collection_promote`; nothing
here runs automatically.

Totality: every validator here reports malformed input as a failure string and
never raises, so one bad collection cannot cost `validate-public-artifacts` the
output of its other groups.

Graph access goes through `GraphIndex`, a thin view over the graph's own CSR
arrays. It never materialises the edge set as Python tuples; an edge lookup
scans one node's neighbour slice. Pure Python, stdlib only (runs on Pi workers).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, TypeGuard
from urllib.parse import urlsplit

from .canonical import content_hash

COLLECTION_SCHEMA_VERSION = 1
COLLECTION_INDEX_SCHEMA_VERSION = 1
PLAYABLE_COHORT_V2_SCHEMA_VERSION = 2

MIN_RECORDS = 4
MAX_RECORDS = 24
MIN_DISTINCT_ARTISTS = 3
MIN_BRIDGE_PLAYERS = 1
MAX_BRIDGE_PLAYERS = 12
MIN_BRIDGE_RECORDS = 2
MIN_BRIDGE_ARTISTS = 2
#: The site's real, user-facing hop budget between people
#: (`findAlbumRoute(..., maxHops = 4)` in `apps/web/src/game/pathfindingGraph.ts`,
#: called with 4 by `connect.ts`). The site's BFS gets that budget PLUS two
#: invisible anchor hops (album -> first performer, last performer -> album),
#: and `stripAlbumAnchors` removes those two, leaving performer-to-performer
#: hops. A route through `via` has `len(via) - 1` such hops (a single shared
#: performer is 0 hops, two total anchor edges). So a published route is
#: reachable by the site's own search iff `len(via) - 1 <= 4`.
MAX_SITE_HOPS = 4
#: Longest route, counted in performers: `MAX_SITE_HOPS + 1`.
MAX_VIA = MAX_SITE_HOPS + 1
MAX_TITLE_CHARS = 120
MAX_INTRO_CHARS = 1500

#: How the builder picks a route. Plain shortest path, first discovered in CSR
#: node order -- NOT the site's ranked recommended route (ADR 0059).
ROUTE_POLICY = "shortest-first-found-v1"

INPUT_NAMES = ("catalog", "pathfinding_graph")

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^collection-v1-[0-9a-f]{12}$")
_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_FILE_NAME = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*)\.v1\.json$")
INDEX_FILE_NAME = "index.v1.json"

# Private-field denylist (ADR 0074). Exact keys at any nesting level, plus any
# key ending `_private`.
PRIVATE_KEYS = frozenset(
    {
        "notes",
        "note",
        "review_note",
        "reviewer",
        "reviewed_by",
        "rejected",
        "working_title",
        "kept_records",
        "input_hash",
        "private",
    }
)
PRIVATE_KEY_SUFFIX = "_private"

# Checked on EVERY string value in the artifact (names, titles and ids
# included). Anchored so ordinary music text is not caught: `/home/` must not
# be preceded by a word character, `local/` is lowercase and must be followed
# by a word character, and so on.
_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("/home/", re.compile(r"(?<!\w)/home/")),
    ("data/private", re.compile(r"data/private")),
    ("local/", re.compile(r"(?<![\w/])local/\w")),
    ("DISCOGS_TOKEN", re.compile(r"DISCOGS_TOKEN")),
    (".ssh", re.compile(r"(?<![\w])\.ssh\b")),
)
# Checked on the owner-written copy only (title, intro, attribution label):
# copy must never suggest the owner's private record collection (ADR 0072 s5).
_OWNER_COLLECTION = re.compile(
    r"\b(?:my (?:own )?(?:record |vinyl )?(?:collection|records|shelf|shelves|library)"
    r"|(?:personal|private) (?:record )?collection)\b",
    re.IGNORECASE,
)
# Title and intro only: copy must not infer influence or a working relationship
# from a shared credit (AGENTS.md). Names and record titles are facts, not claims.
_INFLUENCE = re.compile(r"\b(?:worked with|collaborated with|influenced)\b", re.IGNORECASE)

# Segments that mark a personal page on a music-database or social site.
_URL_DENY_SEGMENTS = frozenset(
    {
        "user",
        "users",
        "collection",
        "mycollection",
        "wantlist",
        "mywantlist",
        "people",
        "profile",
        "seller",
        "sell",
        "lists",
        "list",
    }
)

_TOP_REQUIRED = frozenset(
    {
        "schema_version",
        "collection_id",
        "title",
        "intro",
        "generated_at",
        "records",
        "bridge_players",
        "provenance",
    }
)
_TOP_OPTIONAL = frozenset({"journey", "playable_cohort", "attribution"})
_BRIDGE_KEYS = frozenset({"artist_id", "name", "records"})
_JOURNEY_HOP_KEYS = frozenset(
    {"from_record", "to_record", "via", "via_names", "evidence_release_ids"}
)
_PAIR_KEYS = frozenset(
    {"record_a", "record_b", "hop_count", "via", "via_names", "evidence_release_ids"}
)
_PLAYABLE_KEYS = frozenset({"schema_version", "route_policy", "pairs"})
_ATTRIBUTION_KEYS = frozenset({"label", "source_url"})
_PROVENANCE_KEYS = frozenset({"inputs", "collection_version"})
_INDEX_KEYS = frozenset({"schema_version", "collections"})
_INDEX_ENTRY_KEYS = frozenset(
    {"collection_id", "title", "artifact_path", "record_count", "collection_version"}
)
_COLLECTIONS_KEYS = frozenset({"index", "files", "problems"})


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str(value: Any) -> TypeGuard[str]:
    return isinstance(value, str)


def collection_version(collection: dict[str, Any]) -> str:
    """Content version: a hash of the collection with `provenance` and
    `generated_at` (a label) removed, so it survives re-formatting and
    re-stamping. Pinned by `provenance.collection_version`."""
    identity = {k: v for k, v in collection.items() if k not in ("provenance", "generated_at")}
    return f"collection-v{COLLECTION_SCHEMA_VERSION}-{content_hash(identity, length=12)}"


def collection_artifact_path(collection_id: str) -> str:
    return f"/data/collections/{collection_id}.v1.json"


def artist_key(album: Any) -> Any:
    """A catalog album's primary-artist identity: `artist_id`, else the name."""
    if not isinstance(album, dict):
        return None
    value = album.get("artist_id", album.get("artist"))
    return value if isinstance(value, (int, str)) and not isinstance(value, bool) else None


# ---------------------------------------------------------------- graph view


class GraphIndex:
    """Read-only adjacency lookups over a pathfinding graph payload's CSR."""

    def __init__(self, graph: dict[str, Any]) -> None:
        self.node_ids: list[int] = graph["node_ids"]
        self.names: list[str] = graph["names"]
        self.offsets: list[int] = graph["offsets"]
        self.neighbors: list[int] = graph["neighbors"]
        self.evidence: list[int] = graph["evidence_release_ids"]
        self.index_by_id: dict[int, int] = {n: i for i, n in enumerate(self.node_ids)}
        self._anchor_by_album: dict[str, int] = {}
        for entry in graph.get("album_virtual_nodes") or []:
            index = self.index_by_id.get(entry["virtual_artist_id"])
            if index is not None:
                self._anchor_by_album[entry["album_id"]] = index

    @staticmethod
    def shape_failures(graph: Any) -> list[str]:
        """Why a graph payload cannot be indexed ([] when it can)."""
        if not isinstance(graph, dict):
            return ["pathfinding graph must be an object"]
        for key in ("node_ids", "offsets", "neighbors", "evidence_release_ids"):
            value = graph.get(key)
            if not isinstance(value, list) or not all(_is_int(x) for x in value):
                return [f"pathfinding graph {key} must be an array of integers"]
        names = graph.get("names")
        if not isinstance(names, list) or not all(_is_str(x) for x in names):
            return ["pathfinding graph names must be an array of strings"]
        node_count = len(graph["node_ids"])
        offsets = graph["offsets"]
        if len(names) != node_count or len(offsets) != node_count + 1:
            return ["pathfinding graph arrays are not aligned"]
        if (
            offsets[0] != 0
            or offsets != sorted(offsets)
            or offsets[-1] != len(graph["neighbors"])
            or len(graph["evidence_release_ids"]) != len(graph["neighbors"])
        ):
            return ["pathfinding graph CSR arrays are inconsistent"]
        if any(not 0 <= n < node_count for n in graph["neighbors"]):
            return ["pathfinding graph neighbors contain an invalid node index"]
        nodes = graph.get("album_virtual_nodes")
        if not isinstance(nodes, list) or not all(
            isinstance(e, dict)
            and isinstance(e.get("album_id"), str)
            and _is_int(e.get("virtual_artist_id"))
            for e in nodes
        ):
            return ["pathfinding graph album_virtual_nodes must be an array of anchors"]
        return []

    def slots(self, index: int) -> range:
        return range(self.offsets[index], self.offsets[index + 1])

    def anchor_index(self, album_id: str) -> int | None:
        return self._anchor_by_album.get(album_id)

    def performer_indices(self, album_id: str) -> Iterator[int]:
        """Real (non-anchor) neighbours of the album's anchor, CSR order."""
        anchor = self.anchor_index(album_id)
        if anchor is None:
            return
        for slot in self.slots(anchor):
            n = self.neighbors[slot]
            if self.node_ids[n] > 0:
                yield n

    def adjacent_to_anchor(self, album_id: str, node_id: int) -> bool:
        index = self.index_by_id.get(node_id)
        anchor = self.anchor_index(album_id)
        if index is None or anchor is None:
            return False
        return any(self.neighbors[slot] == index for slot in self.slots(anchor))

    def edge_evidence(self, node_id_a: int, node_id_b: int) -> int | None:
        """The graph's evidence release id on the directed slot a -> b."""
        a, b = self.index_by_id.get(node_id_a), self.index_by_id.get(node_id_b)
        if a is None or b is None:
            return None
        for slot in self.slots(a):
            if self.neighbors[slot] == b:
                return self.evidence[slot]
        return None


# ------------------------------------------------------------------ helpers


def private_field_failures(value: Any, path: str = "$") -> list[str]:
    """Every private key anywhere in `value` (the explicit denylist)."""
    failures: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            where = f"{path}.{key}"
            if isinstance(key, str) and (key in PRIVATE_KEYS or key.endswith(PRIVATE_KEY_SUFFIX)):
                failures.append(f"private field {where!r} must never appear in a public collection")
            failures.extend(private_field_failures(child, where))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            failures.extend(private_field_failures(child, f"{path}[{i}]"))
    return failures


def string_values(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Every string VALUE in a JSON tree with its path (keys excluded)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from string_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from string_values(child, f"{path}[{i}]")


def path_text_failures(value: Any) -> list[str]:
    """Forbidden path/credential substrings in ANY string value."""
    failures: list[str] = []
    for path, text in string_values(value):
        failures.extend(
            f"{path} contains forbidden substring {label!r}"
            for label, pattern in _PATH_PATTERNS
            if pattern.search(text)
        )
    return failures


def copy_failures(label: str, text: str, *, claims: bool) -> list[str]:
    """Owner-written copy: no suggestion of the owner's own collection; and,
    for `claims` copy (title, intro), no inferred influence or working
    relationship."""
    failures = [
        f"{label} contains forbidden phrase {m.group(0).lower()!r}"
        for m in _OWNER_COLLECTION.finditer(text)
    ]
    if claims:
        failures.extend(
            f"{label} contains forbidden phrase {m.group(0).lower()!r}"
            for m in _INFLUENCE.finditer(text)
        )
    return failures


def is_iso_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not _ISO_TIMESTAMP.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def url_failures(label: str, url: Any) -> list[str]:
    """A public source URL: https, a host, no credentials, query or fragment,
    and no personal-page path (user, collection, wantlist, profile, ...)."""
    if not isinstance(url, str) or re.search(r"\s", url) or not url.startswith("https://"):
        return [f"{label} must be an https URL"]
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return [f"{label} is not a valid URL"]
    if not host:
        return [f"{label} must have a host"]
    failures: list[str] = []
    if parts.username is not None or parts.password is not None:
        failures.append(f"{label} must not carry credentials")
    if parts.query or parts.fragment:
        failures.append(f"{label} must not carry a query or fragment")
    for segment in (s.lower() for s in parts.path.split("/") if s):
        if segment in _URL_DENY_SEGMENTS:
            failures.append(
                f"{label} points at a personal page (path segment {segment!r}); a source must "
                "be a public page, never a user, collection, wantlist or profile"
            )
            break
    return failures


def _route_failures(
    label: str,
    from_record: str,
    to_record: str,
    route: dict[str, Any],
    graph: GraphIndex | None,
) -> list[str]:
    via = route.get("via")
    names = route.get("via_names")
    evidence = route.get("evidence_release_ids")
    if (
        not isinstance(via, list)
        or not 1 <= len(via) <= MAX_VIA
        or not all(_is_int(v) and v > 0 for v in via)
    ):
        return [
            f"{label}: via must be 1..{MAX_VIA} positive performer artist ids (at most "
            f"{MAX_SITE_HOPS} hops, the site's own search limit)"
        ]
    if len(set(via)) != len(via):
        return [f"{label}: via repeats a performer"]
    if (
        not isinstance(names, list)
        or len(names) != len(via)
        or not all(isinstance(n, str) and n for n in names)
    ):
        return [f"{label}: via_names must be one non-empty name per via entry"]
    if (
        not isinstance(evidence, list)
        or len(evidence) != len(via) - 1
        or not all(_is_int(e) for e in evidence)
    ):
        return [f"{label}: evidence_release_ids must have one release id per consecutive pair"]
    if graph is None:
        return []
    failures: list[str] = []
    for end, record, performer in ((0, from_record, via[0]), (-1, to_record, via[-1])):
        if graph.anchor_index(record) is None:
            failures.append(f"{label}: record {record!r} has no anchor in the pathfinding graph")
        elif not graph.adjacent_to_anchor(record, performer):
            side = "start" if end == 0 else "end"
            failures.append(
                f"{label}: route {side} performer {performer} is not adjacent to record "
                f"{record!r} in the pathfinding graph"
            )
    for i, performer in enumerate(via):
        index = graph.index_by_id.get(performer)
        if index is None:
            failures.append(f"{label}: performer {performer} is not a node of the graph")
        elif graph.names[index] != names[i]:
            failures.append(
                f"{label}: via_names[{i}] {names[i]!r} does not match the graph's name "
                f"{graph.names[index]!r} for performer {performer}"
            )
    for i in range(len(via) - 1):
        actual = graph.edge_evidence(via[i], via[i + 1])
        if actual is None:
            failures.append(
                f"{label}: no edge between performers {via[i]} and {via[i + 1]} in the "
                "pathfinding graph (the graph changed; re-review and re-promote)"
            )
        elif actual != evidence[i]:
            failures.append(
                f"{label}: evidence release {evidence[i]} for performers {via[i]} -> "
                f"{via[i + 1]} differs from the graph's evidence release {actual}"
            )
    return failures


# ------------------------------------------------------- collection validator


def collection_failures(collection: Any, catalog: Any, graph: Any) -> list[str]:
    """Every contract failure in one collection-v1 artifact, validated against
    the catalog and the pathfinding graph it claims to be a view of. Never
    raises."""
    try:
        return _collection_failures(collection, catalog, graph)
    except Exception as exc:  # last resort: report, never lose other groups
        return [f"collection could not be validated ({type(exc).__name__}: {exc})"]


def _collection_failures(collection: Any, catalog: Any, graph: Any) -> list[str]:
    if not isinstance(collection, dict):
        return ["collection must be an object"]
    failures: list[str] = []
    failures.extend(private_field_failures(collection))
    failures.extend(path_text_failures(collection))

    keys = set(collection)
    if (keys - _TOP_OPTIONAL) != _TOP_REQUIRED:
        missing = sorted(_TOP_REQUIRED - keys)
        extra = sorted(str(k) for k in keys - _TOP_REQUIRED - _TOP_OPTIONAL)
        failures.append(f"collection top-level keys wrong (missing {missing}, unexpected {extra})")
        if missing:
            return failures
    if collection.get("schema_version") != COLLECTION_SCHEMA_VERSION:
        failures.append(f"schema_version must be {COLLECTION_SCHEMA_VERSION}")

    collection_id = collection.get("collection_id")
    if not _is_str(collection_id) or not _SLUG.match(collection_id) or len(collection_id) > 64:
        failures.append("collection_id must be a lowercase slug (a-z, 0-9, hyphens), 1..64 chars")
    for field, limit in (("title", MAX_TITLE_CHARS), ("intro", MAX_INTRO_CHARS)):
        value = collection.get(field)
        if not _is_str(value) or not value.strip():
            failures.append(f"{field} is required for publication and must be non-empty text")
        elif len(value) > limit:
            failures.append(f"{field} must be at most {limit} characters")
        else:
            failures.extend(copy_failures(field, value, claims=True))
    if not is_iso_timestamp(collection.get("generated_at")):
        failures.append("generated_at must be an ISO-8601 timestamp (e.g. 2026-01-01T00:00:00Z)")

    graph_failures = GraphIndex.shape_failures(graph)
    gi: GraphIndex | None = None
    if graph_failures:
        failures.append(
            "pathfinding graph is unusable for collection checks: " + "; ".join(graph_failures)
        )
    else:
        gi = GraphIndex(graph)

    albums = catalog.get("albums") if isinstance(catalog, dict) else None
    album_by_id: dict[str, Any] = {}
    if isinstance(albums, list):
        album_by_id = {
            a["id"]: a for a in albums if isinstance(a, dict) and isinstance(a.get("id"), str)
        }

    records = _record_failures(collection.get("records"), album_by_id, failures)
    record_set = set(records)

    _bridge_failures(collection.get("bridge_players"), record_set, album_by_id, gi, failures)
    if "journey" in collection:
        _journey_failures(collection["journey"], record_set, album_by_id, gi, failures)
    if "playable_cohort" in collection:
        _playable_failures(collection["playable_cohort"], records, album_by_id, gi, failures)
    if "attribution" in collection:
        _attribution_failures(collection["attribution"], failures)
    _provenance_failures(collection, catalog, graph, failures)
    return failures


def _record_failures(records: Any, album_by_id: dict[str, Any], failures: list[str]) -> list[str]:
    if not isinstance(records, list) or not all(isinstance(r, str) and r for r in records):
        failures.append("records must be an array of catalog album id strings")
        return []
    if len(set(records)) != len(records):
        failures.append("records must not contain duplicates")
    if not MIN_RECORDS <= len(records) <= MAX_RECORDS:
        failures.append(
            f"records must hold {MIN_RECORDS}..{MAX_RECORDS} albums, got {len(records)}"
        )
    artists: set[Any] = set()
    for record in records:
        album = album_by_id.get(record)
        if album is None:
            failures.append(f"record {record!r} is not in the catalog")
            continue
        key = artist_key(album)
        if key is not None:
            artists.add(key)
    if len(artists) < MIN_DISTINCT_ARTISTS:
        failures.append(
            f"records must span at least {MIN_DISTINCT_ARTISTS} distinct primary artists, "
            f"got {len(artists)}"
        )
    return list(records)


def _same_artist(a: str, b: str, album_by_id: dict[str, Any]) -> bool:
    key_a, key_b = artist_key(album_by_id.get(a)), artist_key(album_by_id.get(b))
    return key_a is not None and key_a == key_b


def _bridge_failures(
    bridges: Any,
    record_set: set[str],
    album_by_id: dict[str, Any],
    gi: GraphIndex | None,
    failures: list[str],
) -> None:
    if not isinstance(bridges, list) or not (
        MIN_BRIDGE_PLAYERS <= len(bridges) <= MAX_BRIDGE_PLAYERS
    ):
        failures.append(
            f"bridge_players must be an array of {MIN_BRIDGE_PLAYERS}..{MAX_BRIDGE_PLAYERS} players"
        )
        return
    seen: set[int] = set()
    for i, bridge in enumerate(bridges):
        if not isinstance(bridge, dict) or set(bridge) != _BRIDGE_KEYS:
            failures.append(f"bridge_players[{i}] must have exactly keys {sorted(_BRIDGE_KEYS)}")
            continue
        player, name, on = bridge["artist_id"], bridge["name"], bridge["records"]
        label = f"bridge_players[{i}] ({name!r})"
        if not _is_int(player) or player <= 0 or not isinstance(name, str) or not name:
            failures.append(f"{label}: artist_id must be a positive integer and name non-empty")
            continue
        if player in seen:
            failures.append(f"{label}: duplicate bridge player {player}")
        seen.add(player)
        if (
            not isinstance(on, list)
            or not all(isinstance(r, str) for r in on)
            or len(set(on)) != len(on)
            or len(on) < MIN_BRIDGE_RECORDS
        ):
            failures.append(
                f"{label}: records must list at least {MIN_BRIDGE_RECORDS} distinct record ids"
            )
            continue
        for record in on:
            if record not in record_set:
                failures.append(
                    f"{label}: record {record!r} is not one of the collection's records"
                )
            elif gi is not None and not gi.adjacent_to_anchor(record, player):
                failures.append(
                    f"{label}: not adjacent to record {record!r}'s anchor in the pathfinding "
                    "graph (not credited as a performer on it)"
                )
        # A bridge connects DIFFERENT artists' records. A primary artist is
        # adjacent to all of their own albums, so without this rule one artist
        # would "bridge" nothing but their own discography.
        artists = {artist_key(album_by_id.get(r)) for r in on if r in record_set} - {None}
        if len(artists) < MIN_BRIDGE_ARTISTS:
            failures.append(
                f"{label}: records must span at least {MIN_BRIDGE_ARTISTS} distinct primary "
                "artists; a player credited only on one artist's own records bridges nothing"
            )
        if gi is not None:
            index = gi.index_by_id.get(player)
            if index is None:
                failures.append(f"{label}: artist {player} is not a node of the graph")
            elif gi.names[index] != name:
                failures.append(f"{label}: name does not match the graph's {gi.names[index]!r}")


def _journey_failures(
    journey: Any,
    record_set: set[str],
    album_by_id: dict[str, Any],
    gi: GraphIndex | None,
    failures: list[str],
) -> None:
    if not isinstance(journey, list) or not journey:
        failures.append("journey must be a non-empty array of hops")
        return
    visited: list[str] = []
    for i, hop in enumerate(journey):
        if not isinstance(hop, dict) or set(hop) != _JOURNEY_HOP_KEYS:
            failures.append(f"journey[{i}] must have exactly keys {sorted(_JOURNEY_HOP_KEYS)}")
            return
        a, b = hop["from_record"], hop["to_record"]
        label = f"journey hop {i + 1} ({a} -> {b})"
        if not _is_str(a) or not _is_str(b) or a not in record_set or b not in record_set or a == b:
            failures.append(f"{label}: both ends must be distinct records of the collection")
            continue
        if _same_artist(a, b, album_by_id):
            failures.append(
                f"{label}: both records have the same primary artist; a hop must connect "
                "different artists' records"
            )
        if visited and visited[-1] != a:
            failures.append(f"{label}: must start where the previous hop ended ({visited[-1]})")
        if not visited:
            visited.append(a)
        if b in visited:
            failures.append(f"{label}: the journey revisits record {b!r}")
        visited.append(b)
        failures.extend(_route_failures(label, a, b, hop, gi))


def _playable_failures(
    playable: Any,
    records: list[str],
    album_by_id: dict[str, Any],
    gi: GraphIndex | None,
    failures: list[str],
) -> None:
    if not isinstance(playable, dict) or set(playable) != _PLAYABLE_KEYS:
        failures.append(f"playable_cohort must have exactly keys {sorted(_PLAYABLE_KEYS)}")
        return
    if playable["schema_version"] != PLAYABLE_COHORT_V2_SCHEMA_VERSION:
        failures.append(
            f"playable_cohort.schema_version must be {PLAYABLE_COHORT_V2_SCHEMA_VERSION}"
        )
    if playable["route_policy"] != ROUTE_POLICY:
        failures.append(f"playable_cohort.route_policy must be {ROUTE_POLICY!r}")
    pairs = playable["pairs"]
    if not isinstance(pairs, list) or not pairs:
        failures.append("playable_cohort.pairs must be a non-empty array")
        return
    position = {r: i for i, r in enumerate(records)}
    previous: tuple[int, int] | None = None
    for i, pair in enumerate(pairs):
        if not isinstance(pair, dict) or set(pair) != _PAIR_KEYS:
            failures.append(f"playable pair {i} must have exactly keys {sorted(_PAIR_KEYS)}")
            continue
        a, b = pair["record_a"], pair["record_b"]
        label = f"playable pair {i + 1} ({a} -> {b})"
        if not _is_str(a) or not _is_str(b) or a not in position or b not in position:
            failures.append(f"{label}: both records must be records of the collection")
            continue
        if position[a] >= position[b]:
            failures.append(f"{label}: record_a must precede record_b in the collection")
            continue
        if _same_artist(a, b, album_by_id):
            failures.append(
                f"{label}: both records have the same primary artist; a pair must connect "
                "different artists' records"
            )
        key = (position[a], position[b])
        if previous is not None and key <= previous:
            failures.append(f"{label}: pairs must be unique and ordered by collection record order")
        previous = key
        via = pair["via"]
        if _is_int(pair["hop_count"]) and isinstance(via, list):
            if pair["hop_count"] != len(via) - 1:
                failures.append(f"{label}: hop_count must equal len(via) - 1")
        else:
            failures.append(f"{label}: hop_count must be an integer")
        failures.extend(_route_failures(label, a, b, pair, gi))


def _attribution_failures(attribution: Any, failures: list[str]) -> None:
    if not isinstance(attribution, dict) or set(attribution) != _ATTRIBUTION_KEYS:
        failures.append(f"attribution must have exactly keys {sorted(_ATTRIBUTION_KEYS)}")
        return
    label = attribution["label"]
    if not _is_str(label) or not label.strip():
        failures.append("attribution.label must be non-empty text")
    else:
        failures.extend(copy_failures("attribution.label", label, claims=False))
    failures.extend(url_failures("attribution.source_url", attribution["source_url"]))


def _current_versions(catalog: Any, graph: Any) -> dict[str, Any]:
    return {
        "catalog": catalog.get("catalog_version") if isinstance(catalog, dict) else None,
        "pathfinding_graph": (
            graph.get("pathfinding_graph_version") if isinstance(graph, dict) else None
        ),
    }


def _provenance_failures(
    collection: dict[str, Any], catalog: Any, graph: Any, failures: list[str]
) -> None:
    provenance = collection.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != _PROVENANCE_KEYS:
        failures.append(f"provenance must have exactly keys {sorted(_PROVENANCE_KEYS)}")
        return
    inputs = provenance["inputs"]
    if not isinstance(inputs, dict) or set(inputs) != set(INPUT_NAMES):
        failures.append(f"provenance.inputs must declare exactly {list(INPUT_NAMES)}")
    else:
        current = _current_versions(catalog, graph)
        for name in INPUT_NAMES:
            declared = inputs[name]
            if not _is_str(declared) or not declared:
                failures.append(f"provenance.inputs[{name!r}] must be a version string")
            elif declared != current[name]:
                failures.append(
                    f"collection was built from {name} version {declared!r} but the current "
                    f"{name} is {current[name]!r} -- re-run promote-collection and re-review"
                )
    declared_version = provenance["collection_version"]
    if not _is_str(declared_version) or not _VERSION.match(declared_version):
        failures.append("provenance.collection_version is not well-formed")
    else:
        expected = collection_version(collection)
        if declared_version != expected:
            failures.append(
                f"provenance.collection_version {declared_version!r} does not match recomputed "
                f"content (expected {expected!r})"
            )


# ------------------------------------------------------------ index + group


def load_collections_directory(directory: Path) -> dict[str, Any] | None:
    """Load `collections/` for validation: `None` when the directory does not
    exist (nothing published: valid). EVERY entry is accounted for: the index,
    `<id>.v1.json` files, and everything else (other names, subdirectories,
    symlinks) is reported in `problems` so a stray private file cannot sit in a
    served directory unchecked. Unreadable or malformed JSON is also a problem,
    never an exception."""
    if not directory.is_dir():
        return None
    index: Any = None
    files: dict[str, Any] = {}
    problems: list[str] = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        name = entry.name
        match = _FILE_NAME.match(name)
        if entry.is_symlink() or not entry.is_file() or (name != INDEX_FILE_NAME and not match):
            problems.append(
                f"unexpected entry {name!r} in collections/: only {INDEX_FILE_NAME} and "
                "<id>.v1.json files listed in it may be published"
            )
            continue
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{name} is unreadable or not valid JSON ({type(exc).__name__})")
            continue
        if name == INDEX_FILE_NAME:
            index = payload
        elif match:
            files[match.group(1)] = payload
    return {"index": index, "files": files, "problems": problems}


def collections_failures(collections: Any, catalog: Any, graph: Any) -> list[str]:
    """The `collections` group. `collections` is `None` (no collections
    directory: passes) or what `load_collections_directory` returns:
    `{"index", "files": {collection_id: payload}, "problems"?: [str]}`. Every
    collection the index lists is validated; a collection file not listed in
    the index, and every loader problem, is a failure. Never raises."""
    try:
        return _collections_failures(collections, catalog, graph)
    except Exception as exc:  # last resort: report, never lose other groups
        return [f"collections could not be validated ({type(exc).__name__}: {exc})"]


def _collections_failures(collections: Any, catalog: Any, graph: Any) -> list[str]:
    if collections is None:
        return []
    if (
        not isinstance(collections, dict)
        or not {"index", "files"} <= set(collections)
        or set(collections) - _COLLECTIONS_KEYS
    ):
        return ["collections must be an object with keys 'index', 'files' and optional 'problems'"]
    index, files = collections["index"], collections["files"]
    problems = collections.get("problems") or []
    failures: list[str] = [str(p) for p in problems] if isinstance(problems, list) else []
    if not isinstance(files, dict):
        return [*failures, "collections files must be an object keyed by collection_id"]
    if index is None:
        failures.extend(
            f"collection file {cid!r} exists but there is no collections index" for cid in files
        )
        return failures
    if not isinstance(index, dict) or set(index) != _INDEX_KEYS:
        return [*failures, f"collections index must have exactly keys {sorted(_INDEX_KEYS)}"]
    if index["schema_version"] != COLLECTION_INDEX_SCHEMA_VERSION:
        failures.append(
            f"collections index schema_version must be {COLLECTION_INDEX_SCHEMA_VERSION}"
        )
    entries = index["collections"]
    if not isinstance(entries, list):
        return [*failures, "collections index 'collections' must be an array"]
    ids: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != _INDEX_ENTRY_KEYS:
            failures.append(f"index entry {i} must have exactly keys {sorted(_INDEX_ENTRY_KEYS)}")
            continue
        cid = entry["collection_id"]
        if not _is_str(cid):
            failures.append(f"index entry {i} collection_id must be a string")
            continue
        ids.append(cid)
        failures.extend(path_text_failures(entry))
        if entry["artifact_path"] != collection_artifact_path(cid):
            failures.append(
                f"index entry {cid!r} artifact_path must be {collection_artifact_path(cid)!r}"
            )
        payload = files.get(cid)
        if payload is None:
            failures.append(f"index lists collection {cid!r} but no file was loaded for it")
            continue
        if isinstance(payload, dict):
            provenance = payload.get("provenance")
            file_version = (
                provenance.get("collection_version") if isinstance(provenance, dict) else None
            )
            if payload.get("collection_id") != cid:
                failures.append(f"index entry {cid!r} does not match the file's collection_id")
            if payload.get("title") != entry["title"]:
                failures.append(f"index entry {cid!r} title does not match the file's")
            if entry["collection_version"] != file_version:
                failures.append(f"index entry {cid!r} collection_version does not match the file's")
            records = payload.get("records")
            if entry["record_count"] != (len(records) if isinstance(records, list) else None):
                failures.append(f"index entry {cid!r} record_count does not match the file's")
        failures.extend(f"{cid}: {f}" for f in collection_failures(payload, catalog, graph))
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        failures.append("collections index entries must be unique and sorted by collection_id")
    failures.extend(
        f"collection file {cid!r} is not listed in the collections index"
        for cid in sorted(set(files) - set(ids))
    )
    return failures


def dumps_stable(value: Any) -> str:
    """Stable text form used by builders (sorted keys, 2-space indent). Not
    Prettier-shaped: `apps/web/.prettierignore` lists `public/data/collections/`
    so a re-run of Prettier never rewrites it."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
