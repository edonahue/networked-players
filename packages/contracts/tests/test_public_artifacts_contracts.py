"""Cross-checks `public_artifacts_failures` against each individual
validator it wraps, and proves the whole point of this module: a real
defect in any one artifact (here, a deleted `mode` key on Record Routes) is
caught by the combined check, not silently missed."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from networked_players_contracts import public_artifacts_failures
from networked_players_contracts.album_art import album_art_version
from networked_players_contracts.album_credit_membership import album_credit_membership_version
from networked_players_contracts.album_hop_distances import album_hop_distances_version
from networked_players_contracts.canonical import content_hash, stable_id_digest
from networked_players_contracts.catalog import _catalog_version
from networked_players_contracts.connection_rounds import round_content_fingerprint
from networked_players_contracts.contributor_index import contributor_index_version
from networked_players_contracts.evidence_release_registry import (
    evidence_release_registry_version,
)
from networked_players_contracts.pathfinding_graph import pathfinding_graph_version
from networked_players_contracts.prominence import prominence_version
from networked_players_contracts.search_index import search_index_version

_SNAPSHOT = "20260601"


# --- catalog + album-art registry -------------------------------------------


_FIXTURE_TITLES = {"master-1": "First Light", "master-2": "Third Wave"}
_FIXTURE_ARTISTS = {"master-1": "Alice", "master-2": "Cara"}


def _catalog_album(album_id: str, *, artist_id: int, main_release_id: int) -> dict[str, Any]:
    return {
        "id": album_id,
        "master_id": int(album_id.split("-")[1]),
        "main_release_id": main_release_id,
        "title": _FIXTURE_TITLES.get(album_id, album_id.title()),
        "artist_id": artist_id,
        "artist": _FIXTURE_ARTISTS.get(album_id, "Alice"),
        "year": 1995,
    }


def _synthetic_pool(catalog: dict[str, Any]) -> dict[str, Any]:
    """A pool covering exactly the synthetic catalog's masters (these v1-shaped
    fixtures carry no round/label fields, so only the master set is compared)."""
    return {
        "schema_version": 1,
        "note": "synthetic",
        "albums": [
            {"master_id": a["master_id"], "round": 0, "selection_source": "editorial"}
            for a in sorted(catalog["albums"], key=lambda a: a["master_id"])
        ],
    }


def _catalog() -> dict[str, Any]:
    albums = [
        _catalog_album("master-1", artist_id=100, main_release_id=1),
        _catalog_album("master-2", artist_id=200, main_release_id=2),
    ]
    return {
        "catalog_version": _catalog_version(albums, _SNAPSHOT),
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-master-2atalog 0.1.0",
        "albums": albums,
    }


def _album_art_registry() -> dict[str, Any]:
    entries = [
        {
            "album_id": "master-1",
            "main_release_id": 1,
            "uri150": "https://i.discogs.com/a/150.jpg",
            "uri": "https://i.discogs.com/a/full.jpg",
            "width": 600,
            "height": 600,
        }
    ]
    return {
        "schema_version": 1,
        "catalog_version": _catalog()["catalog_version"],
        "art_version": album_art_version(entries, _SNAPSHOT),
        "generated_at": "2026-07-22T00:00:00+00:00",
        "source": "Discogs API /releases/{id} images",
        "license": "presentational only",
        "albums": entries,
    }


# --- Connection Guesser ------------------------------------------------------

_CONNECTION_ROUND_ID = f"conn-{stable_id_digest('1h', 'master-1', 'master-2', '700')}"


def _connection_round() -> dict[str, Any]:
    return {
        "id": _CONNECTION_ROUND_ID,
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": "hard",
        "endpoints": [
            {
                "id": "master-1",
                "title": "First Light",
                "year": 1995,
                "act": "Alice",
                "label": None,
                "art": None,
            },
            {
                "id": "master-2",
                "title": "Third Wave",
                "year": 1996,
                "act": "Cara",
                "label": None,
                "art": None,
            },
        ],
        "answer_set": [{"id": 700, "name": "Xavier", "role_category": "guitar"}],
        "distractors": [],
        "clues": [],
        "evidence": [
            {
                "release_ref": "master-1",
                "release_title": "First Light",
                "contributor_id": 700,
                "credited_as": "Xavier",
                "role_text": "Guitar",
                "credit_scope": "release_credit",
            },
            {
                "release_ref": "master-2",
                "release_title": "Third Wave",
                "contributor_id": 700,
                "credited_as": "Xavier",
                "role_text": "Guitar",
                "credit_scope": "release_credit",
            },
        ],
        "provenance_note": "Real records: derived from the Discogs monthly data dump (CC0).",
    }


def _connection_artifact_version(rounds: list[dict[str, Any]]) -> str:
    fingerprints = [round_content_fingerprint(r) for r in rounds]
    digest = content_hash(fingerprints, length=12)
    return f"connection-artifact-v1-{_SNAPSHOT}-{digest}"


_CONNECTION_PROVENANCE = {
    "source": "Discogs monthly data dump (CC0), one-hop working set",
    "license": "See docs/DATA_AND_RIGHTS.md.",
    "snapshot_date": _SNAPSHOT,
    "generated_by": "networked-players-catalog build-connection-rounds 0.1.0",
    "catalog_version": _catalog()["catalog_version"],
    "pool_version": "connection-v1-20260601-def456def456",
    "artifact_version": _connection_artifact_version([_connection_round()]),
    "note": "Real records, not synthetic.",
}


def _connection_universe() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": dict(_CONNECTION_PROVENANCE),
        "albums": [
            {
                "id": "master-1",
                "title": "First Light",
                "act": "Alice",
                "act_id": 100,
                "year": 1995,
                "label": None,
                "art": None,
            },
            {
                "id": "master-2",
                "title": "Third Wave",
                "act": "Cara",
                "act_id": 300,
                "year": 1996,
                "label": None,
                "art": None,
            },
        ],
        "contributors": [{"id": 700, "name": "Xavier", "role_category": "guitar"}],
        "releases": [
            {
                "id": "master-1",
                "album_id": "master-1",
                "title": "First Light",
                "year": 1995,
                "catalog_stamp": "DISCOGS-1",
            },
            {
                "id": "master-2",
                "album_id": "master-2",
                "title": "Third Wave",
                "year": 1996,
                "catalog_stamp": "DISCOGS-2",
            },
        ],
        "credits": [
            {
                "release_id": "master-1",
                "contributor_id": 700,
                "role_text": "Guitar",
                "role_category": "guitar",
                "credit_scope": "release_credit",
            },
            {
                "release_id": "master-2",
                "contributor_id": 700,
                "role_text": "Guitar",
                "role_category": "guitar",
                "credit_scope": "release_credit",
            },
        ],
    }


def _connection_rounds() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provenance": dict(_CONNECTION_PROVENANCE),
        "rounds": [_connection_round()],
    }


# --- Connection-daily-manifest -----------------------------------------------


def _daily_manifest() -> dict[str, Any]:
    round_json = _connection_round()
    return {
        "schema_version": 1,
        "mode": "connection_guesser_one_hop",
        "catalog_version": _catalog()["catalog_version"],
        "pool_version": _CONNECTION_PROVENANCE["pool_version"],
        "artifact_version": _CONNECTION_PROVENANCE["artifact_version"],
        "generated_at": "2026-07-22T00:00:00+00:00",
        "start_date": "2026-07-22",
        "schedule": [
            {
                "date": "2026-07-22",
                "round_id": round_json["id"],
                "round_fingerprint": round_content_fingerprint(round_json),
            }
        ],
    }


# --- Record Routes ------------------------------------------------------------


def _route_hop(release_id: int, a: int, b: int) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "artist_a_id": a,
        "artist_b_id": b,
        "role_a": "Guitar",
        "role_b": "Bass",
        "quality_flags": ["performer_credit", "same_recording"],
    }


def _route() -> dict[str, Any]:
    endpoints = sorted(("master-1", "master-2"))
    route_id = f"route-{stable_id_digest('rr', *endpoints, '500:100:200')}"
    return {
        "id": route_id,
        "kind": "one_hop",
        "difficulty": "medium",
        "from_album_id": "master-1",
        "to_album_id": "master-2",
        "from_artist_id": 100,
        "to_artist_id": 200,
        "hops": [_route_hop(500, 100, 200)],
        "distractors": [],
    }


def _routes_releases_and_artists(
    routes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Minimal `rounds.releases[]`/`rounds.artists[]` entries covering every
    hop reference in `routes` -- record_routes_failures checks every hop's
    release_id/artist_a_id/artist_b_id resolve against these."""
    release_ids: set[int] = set()
    artist_ids: set[int] = set()
    for route in routes:
        for hop in route["hops"]:
            release_ids.add(hop["release_id"])
            artist_ids.add(hop["artist_a_id"])
            artist_ids.add(hop["artist_b_id"])
    releases = [{"release_id": rid, "title": f"Release {rid}"} for rid in sorted(release_ids)]
    artists = [{"artist_id": aid, "name": f"Artist {aid}"} for aid in sorted(artist_ids)]
    return releases, artists


def _routes_provenance(
    albums: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    artists: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {"albums": albums, "rounds": rounds, "releases": releases, "artists": artists}
    return {
        "source": "Discogs monthly data dump (CC0), one-hop working set",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "snapshot_date": _SNAPSHOT,
        "generated_by": "networked-players-catalog build-record-routes 0.1.0",
        "graph_core_version": "0.1.0",
        "note": "Real path evidence.",
        "catalog_version": _catalog()["catalog_version"],
        "artifact_version": (f"routes-artifact-v1-{_SNAPSHOT}-{content_hash(payload, length=12)}"),
    }


def _routes_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    routes = [_route()]
    albums = [
        _catalog_album("master-1", artist_id=100, main_release_id=1),
        _catalog_album("master-2", artist_id=200, main_release_id=2),
    ]
    releases, artists = _routes_releases_and_artists(routes)
    pool_version = (
        f"routes-v1-{_SNAPSHOT}-{content_hash(sorted(r['id'] for r in routes), length=12)}"
    )
    prov = _routes_provenance(albums, routes, releases, artists)
    universe = {
        "schema_version": 1,
        "mode": "record_routes",
        "pool_version": pool_version,
        "provenance": prov,
        "counts": {"one_hop": 1, "two_hop": 0, "daily_eligible": 1},
        "albums": albums,
    }
    rounds = {
        "schema_version": 1,
        "mode": "record_routes",
        "pool_version": pool_version,
        "provenance": prov,
        "rounds": routes,
        "releases": releases,
        "artists": artists,
    }
    return universe, rounds


# --- challenge --------------------------------------------------------


def _challenge_release(release_id: int, title: str) -> dict[str, Any]:
    return {
        "snapshot_date": _SNAPSHOT,
        "release_id": release_id,
        "status": "Accepted",
        "title": title,
        "country": None,
        "released": "1995",
        "master_id": None,
        "master_is_main_release": None,
        "data_quality": None,
        "source_url": f"https://example.invalid/release/{release_id}",
        "credits": [],
    }


def _challenge() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "provenance": {
            "source": "Discogs monthly data dump (CC0), one-hop working set",
            "license": "Derived from the Discogs monthly CC0 data dumps. See "
            "docs/DATA_AND_RIGHTS.md.",
            "snapshot_date": _SNAPSHOT,
            "generated_by": "networked-players-catalog build-challenge-from-dump 0.1.0",
            "graph_core_version": "0.1.0",
            "catalog_version": _catalog()["catalog_version"],
            "graph_policy_version": 1,
            "note": "Derived from a bounded one-hop working set.",
        },
        "albums": [
            _catalog_album("master-1", artist_id=100, main_release_id=1),
            _catalog_album("master-2", artist_id=200, main_release_id=2),
        ],
        "artists": [{"artist_id": 100, "name": "Alice"}, {"artist_id": 200, "name": "Bob"}],
        "paths": [
            {
                "id": "path-1",
                "hops": [{"release_id": 1, "artist_a_id": 100, "artist_b_id": 200}],
            }
        ],
        "releases": [
            _challenge_release(1, "Alpha's Album"),
            _challenge_release(2, "Bravo's Album"),
        ],
    }


# --- contributor index -----------------------------------------------------


def _contributor_index() -> dict[str, Any]:
    catalog_version = _catalog()["catalog_version"]
    contributors = [
        {
            "artist_id": 100,
            "name": "Alice",
            "role_categories": ["strings"],
            "role_text_examples": ["Guitar"],
            "albums": ["master-1", "master-2"],
            "decade_activity": [1990],
            "connection_count": 1,
            "neighboring_contributor_ids": [200],
            "evidence": [{"release_id": 1, "role_text": "Guitar"}],
            "interesting_next_step": None,
        },
        {
            "artist_id": 200,
            "name": "Bob",
            "role_categories": ["strings"],
            "role_text_examples": ["Bass"],
            "albums": ["master-1", "master-2"],
            "decade_activity": [1990],
            "connection_count": 1,
            "neighboring_contributor_ids": [100],
            "evidence": [{"release_id": 1, "role_text": "Bass"}],
            "interesting_next_step": None,
        },
    ]
    return {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "contributor_index_version": contributor_index_version(contributors, _SNAPSHOT),
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Derived from challenge.v3.json and routes/{universe,rounds}.v1.json.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "contributors": contributors,
    }


# --- album-hop-distances (ADR 0048 addendum) ----------------------------------


def _album_hop_distances() -> dict[str, Any]:
    catalog_version = _catalog()["catalog_version"]
    entries = [
        {"artist_id": 100, "album_id": "master-1", "hop_distance": 0},
        {"artist_id": 100, "album_id": "master-2", "hop_distance": 1},
        {"artist_id": 200, "album_id": "master-2", "hop_distance": 0},
        {"artist_id": 200, "album_id": "master-1", "hop_distance": 1},
    ]
    return {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "album_hop_distances_version": album_hop_distances_version(entries, _SNAPSHOT),
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source": "Derived from challenge.v3.json and routes/rounds.v1.json.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "entries": entries,
    }


# --- pathfinding graph -------------------------------------------------------


_PATHFINDING_ANCHOR_SENTINEL = "__np_album_anchor__"


def _pathfinding_graph_v3() -> dict[str, Any]:
    """Two catalog albums (master-1/artist 100, master-2/artist 200), one
    real edge between them (release 1), and one virtual anchor per album
    connected to its own credited artist. Schema 3, the retired
    pre-dictionary-encoding shape (ADR 0068), kept as the base content for
    `_pathfinding_graph()`'s real schema-4 shape (ADR 0071). node_ids
    sorted: [-2 (master-2 anchor), -1 (master-1 anchor), 100, 200]."""
    catalog_version = _catalog()["catalog_version"]
    payload: dict[str, Any] = {
        "schema_version": 3,
        "graph_policy_version": 1,
        "catalog_version": catalog_version,
        "snapshot_date": _SNAPSHOT,
        "generated_at": "2026-08-08T00:00:00+00:00",
        "source": "Discogs monthly data dump (CC0), one-hop working set.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "node_ids": [-2, -1, 100, 200],
        "names": ["Second Wave (album anchor)", "First Light (album anchor)", "Alice", "Bob"],
        "offsets": [0, 1, 2, 4, 6],
        "neighbors": [3, 2, 1, 3, 0, 2],
        "evidence_release_ids": [2, 1, 1, 1, 2, 1],
        "edge_role_a": [
            _PATHFINDING_ANCHOR_SENTINEL,
            _PATHFINDING_ANCHOR_SENTINEL,
            "Guitar",
            "Guitar",
            "Bass",
            "Bass",
        ],
        "edge_role_b": [
            "Bass",
            "Guitar",
            _PATHFINDING_ANCHOR_SENTINEL,
            "Bass",
            _PATHFINDING_ANCHOR_SENTINEL,
            "Guitar",
        ],
        "album_virtual_nodes": [
            {"album_id": "master-1", "virtual_artist_id": -1, "main_release_id": 1},
            {"album_id": "master-2", "virtual_artist_id": -2, "main_release_id": 2},
        ],
    }
    payload["pathfinding_graph_version"] = pathfinding_graph_version(payload, _SNAPSHOT)
    return payload


def _pathfinding_graph() -> dict[str, Any]:
    """Same real content as `_pathfinding_graph_v3()`, dictionary-encoded
    (ADR 0071, graph-expansion Phase 1): a new `roles` array,
    `edge_role_a`/`edge_role_b` become indices into it. Schema 4, the only
    published pathfinding graph as of the retirement of v3."""
    v3 = _pathfinding_graph_v3()
    roles: list[str] = []
    index: dict[str, int] = {}

    def role_id(text: str) -> int:
        if text not in index:
            index[text] = len(roles)
            roles.append(text)
        return index[text]

    payload = {
        **v3,
        "schema_version": 4,
        "roles": roles,
        "edge_role_a": [role_id(t) for t in v3["edge_role_a"]],
        "edge_role_b": [role_id(t) for t in v3["edge_role_b"]],
    }
    payload["pathfinding_graph_version"] = pathfinding_graph_version(payload, _SNAPSHOT)
    return payload


def _prominence(pathfinding_graph: dict[str, Any]) -> dict[str, Any]:
    """A minimal, structurally-valid companion to `_pathfinding_graph()`
    (graph-expansion Phase 1, plan section 8) -- node-aligned with its
    `node_ids`, every value zero/null (this fixture only needs to be
    CLEAN, not realistic)."""
    node_ids = pathfinding_graph["node_ids"]
    node_count = len(node_ids)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": pathfinding_graph["catalog_version"],
        "pathfinding_graph_version": pathfinding_graph["pathfinding_graph_version"],
        "generated_at": "2026-09-03T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "node_ids": node_ids,
        "degree": [0] * node_count,
        "albums_1hop": [0] * node_count,
        "albums_2hop": [0] * node_count,
        "evidence_releases": [0] * node_count,
        "role_diversity": [0] * node_count,
        "first_year": [None] * node_count,
        "last_year": [None] * node_count,
        "rank": [0] * node_count,
    }
    payload["prominence_version"] = prominence_version(payload, _SNAPSHOT)
    return payload


# --- album-credit-membership --------------------------------------------------


def _album_credit_membership() -> dict[str, Any]:
    catalog_version = _catalog()["catalog_version"]
    albums = [
        {
            "album_id": "master-1",
            "main_release_id": 1,
            "credits": [
                {
                    "artist_id": 100,
                    "name": "Alice",
                    "anv": None,
                    "role_text": "Guitar",
                    "credit_scope": "release_artist",
                    "track_position": None,
                    "track_title": None,
                }
            ],
        },
        {
            "album_id": "master-2",
            "main_release_id": 2,
            "credits": [
                {
                    "artist_id": 200,
                    "name": "Bob",
                    "anv": None,
                    "role_text": "Bass",
                    "credit_scope": "release_artist",
                    "track_position": None,
                    "track_title": None,
                }
            ],
        },
    ]
    return {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "album_credit_membership_version": album_credit_membership_version(albums, _SNAPSHOT),
        "generated_at": "2026-08-07T00:00:00+00:00",
        "source": "Derived from each album's own main_release_id.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        "albums": albums,
    }


# --- evidence-release registry ------------------------------------------------


def _evidence_release_registry() -> dict[str, Any]:
    catalog_version = _catalog()["catalog_version"]
    fields = {
        "release_ids": [1, 2, 500],
        "titles": ["First Light", "Second Wave", "Third Wave"],
        "years": [1995, 1998, 1999],
        "countries": ["US", "US", "US"],
        "master_ids": [None, None, None],
        "source_urls": ["https://data.discogs.com/?download=fake"] * 3,
        "cover_uri150s": [None, None, None],
        "relation_to_catalog_album_ids": ["master-1", "master-2", "master-2"],
    }
    registry = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "generated_at": "2026-08-07T00:00:00+00:00",
        "source": "Union of challenge/routes/pathfinding-graph release ids.",
        "license": "See docs/DATA_AND_RIGHTS.md.",
        **fields,
    }
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    return registry


# --- search index --------------------------------------------------------------


def _search_index() -> dict[str, Any]:
    catalog = _catalog()
    contributor_index = _contributor_index()
    entries = [
        {
            "kind": "album",
            "id": album["id"],
            "label": album["title"],
            "sublabel": album["artist"],
            "state": "present",
        }
        for album in catalog["albums"]
    ] + [
        {
            "kind": "contributor",
            "id": str(contributor["artist_id"]),
            "label": contributor["name"],
            "sublabel": None,
            "state": "present",
        }
        for contributor in contributor_index["contributors"]
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": catalog["catalog_version"],
        "contributor_index_version": contributor_index["contributor_index_version"],
        "generated_at": "2026-09-03T00:00:00+00:00",
        "source": "test",
        "license": "test",
        "entries": entries,
    }
    payload["search_index_version"] = search_index_version(entries, _SNAPSHOT)
    return payload


# --- the combined check -------------------------------------------------------


def _clean_artifacts() -> dict[str, Any]:
    routes_universe, routes_rounds = _routes_pair()
    pathfinding_graph = _pathfinding_graph()
    return {
        "catalog": _catalog(),
        "album_art": _album_art_registry(),
        "connection_universe": _connection_universe(),
        "connection_rounds": _connection_rounds(),
        "daily_manifest": _daily_manifest(),
        "routes_universe": routes_universe,
        "routes_rounds": routes_rounds,
        "challenge": _challenge(),
        "contributor_index": _contributor_index(),
        "album_hop_distances": _album_hop_distances(),
        "pathfinding_graph": pathfinding_graph,
        "prominence": _prominence(pathfinding_graph),
        "album_credit_membership": _album_credit_membership(),
        "evidence_release_registry": _evidence_release_registry(),
        "search_index": _search_index(),
        "approved_pool": _synthetic_pool(_catalog()),
    }


def test_clean_publication_set_has_no_failures() -> None:
    report = public_artifacts_failures(**_clean_artifacts())
    assert report == {
        "catalog": [],
        "album_art_registry": [],
        "connection_guesser": [],
        "connection_daily_manifest": [],
        "record_routes": [],
        "challenge": [],
        "contributor_index": [],
        "album_hop_distances": [],
        "pathfinding_graph": [],
        "prominence": [],
        "album_credit_membership": [],
        "evidence_release_registry": [],
        "search_index": [],
        "approved_pool": [],
    }


def test_every_group_key_always_present() -> None:
    report = public_artifacts_failures(**_clean_artifacts())
    assert set(report) == {
        "catalog",
        "album_art_registry",
        "connection_guesser",
        "connection_daily_manifest",
        "record_routes",
        "challenge",
        "contributor_index",
        "album_hop_distances",
        "pathfinding_graph",
        "prominence",
        "album_credit_membership",
        "evidence_release_registry",
        "search_index",
        "approved_pool",
    }


def test_approved_pool_group_catches_a_missing_pool_and_an_unapproved_album() -> None:
    artifacts = _clean_artifacts()
    shrunk = deepcopy(artifacts["approved_pool"])
    shrunk["albums"] = shrunk["albums"][:1]
    report = public_artifacts_failures(**{**artifacts, "approved_pool": shrunk})
    assert any("not in the approved pool" in f for f in report["approved_pool"])
    without = public_artifacts_failures(**{**artifacts, "approved_pool": None})
    assert any("not supplied" in f for f in without["approved_pool"])


def test_deleted_mode_on_record_routes_is_caught() -> None:
    """The exact regression this module exists to prevent: a real defect in
    one committed artifact must surface in the combined report, not be
    silently missed because nothing ever ran the real validator against it."""
    artifacts = _clean_artifacts()
    broken_universe = deepcopy(artifacts["routes_universe"])
    broken_rounds = deepcopy(artifacts["routes_rounds"])
    del broken_universe["mode"]
    del broken_rounds["mode"]
    artifacts["routes_universe"] = broken_universe
    artifacts["routes_rounds"] = broken_rounds

    report = public_artifacts_failures(**artifacts)
    assert report["record_routes"] != []
    assert any("mode" in f for f in report["record_routes"])
    # Every other artifact stays clean -- one defect doesn't mask another.
    assert report["catalog"] == []
    assert report["album_art_registry"] == []
    assert report["connection_guesser"] == []
    assert report["connection_daily_manifest"] == []
    assert report["challenge"] == []
    assert report["contributor_index"] == []


def test_catalog_defect_is_caught_independently() -> None:
    artifacts = _clean_artifacts()
    broken_catalog = deepcopy(artifacts["catalog"])
    # `year` is not compared by any downstream catalog-aware check, so this
    # defect stays isolated to the catalog group (a missing title would now,
    # correctly, also surface as a title mismatch in every dependent pool).
    del broken_catalog["albums"][0]["year"]
    artifacts["catalog"] = broken_catalog

    report = public_artifacts_failures(**artifacts)
    assert report["catalog"] != []
    assert report["record_routes"] == []
    assert report["challenge"] == []
    assert report["contributor_index"] == []


def test_deleted_provenance_field_on_challenge_is_caught() -> None:
    """Finding B's required regression test: challenge.v3.json was never
    part of this gate before -- deleting a required provenance field must
    surface in the combined report, isolated to the challenge group."""
    artifacts = _clean_artifacts()
    broken_challenge = deepcopy(artifacts["challenge"])
    del broken_challenge["provenance"]["license"]
    artifacts["challenge"] = broken_challenge

    report = public_artifacts_failures(**artifacts)
    assert report["challenge"] != []
    assert any("provenance.license" in f for f in report["challenge"])
    assert report["catalog"] == []
    assert report["album_art_registry"] == []
    assert report["connection_guesser"] == []
    assert report["connection_daily_manifest"] == []
    assert report["record_routes"] == []
    assert report["contributor_index"] == []


def test_contributor_index_defect_is_caught_independently() -> None:
    artifacts = _clean_artifacts()
    broken_index = deepcopy(artifacts["contributor_index"])
    del broken_index["contributors"][0]["name"]
    artifacts["contributor_index"] = broken_index

    report = public_artifacts_failures(**artifacts)
    assert report["contributor_index"] != []
    assert report["catalog"] == []
    assert report["challenge"] == []
    assert report["record_routes"] == []


def test_album_hop_distances_defect_is_caught_independently() -> None:
    artifacts = _clean_artifacts()
    broken = deepcopy(artifacts["album_hop_distances"])
    broken["entries"][0]["hop_distance"] = -1
    artifacts["album_hop_distances"] = broken

    report = public_artifacts_failures(**artifacts)
    assert report["album_hop_distances"] != []
    assert report["catalog"] == []
    assert report["challenge"] == []
    assert report["contributor_index"] == []


def test_pathfinding_graph_defect_is_caught_independently() -> None:
    artifacts = _clean_artifacts()
    broken = deepcopy(artifacts["pathfinding_graph"])
    broken["album_virtual_nodes"][0]["virtual_artist_id"] = 1  # must be negative
    artifacts["pathfinding_graph"] = broken

    report = public_artifacts_failures(**artifacts)
    assert report["pathfinding_graph"] != []
    assert report["catalog"] == []
    assert report["challenge"] == []
    assert report["contributor_index"] == []


# --- catalog lineage: cross-artifact checks that need the catalog -------------
#
# Each test makes exactly ONE artifact stale or inconsistent against an
# otherwise-clean set and asserts the specific group reports a clear message.


def _with_regenerated_catalog(artifacts: dict[str, Any]) -> dict[str, Any]:
    """The 'operator regenerated the catalog and forgot to rebuild the pools'
    scenario: a valid catalog with one more album, so its catalog_version
    changes, while every pool artifact keeps the old version."""
    catalog = deepcopy(artifacts["catalog"])
    catalog["albums"].append(_catalog_album("master-3", artist_id=300, main_release_id=3))
    catalog["catalog_version"] = _catalog_version(catalog["albums"], _SNAPSHOT)
    artifacts = dict(artifacts)
    artifacts["catalog"] = catalog
    return artifacts


def test_unmodified_fixtures_pass_the_lineage_checks() -> None:
    report = public_artifacts_failures(**_clean_artifacts())
    for group in (
        "connection_guesser",
        "record_routes",
        "challenge",
        "evidence_release_registry",
        "search_index",
    ):
        assert report[group] == [], group


def test_connection_pool_built_against_an_older_catalog_is_caught() -> None:
    artifacts = _with_regenerated_catalog(_clean_artifacts())
    report = public_artifacts_failures(**artifacts)
    assert any("catalog_version" in f for f in report["connection_guesser"])


def test_connection_universe_album_missing_from_catalog_is_caught() -> None:
    artifacts = _clean_artifacts()
    universe = deepcopy(artifacts["connection_universe"])
    universe["albums"][0]["id"] = "master-99"
    artifacts["connection_universe"] = universe
    report = public_artifacts_failures(**artifacts)
    assert any("master-99" in f and "catalog" in f for f in report["connection_guesser"])


def test_connection_universe_retitled_album_is_caught() -> None:
    artifacts = _clean_artifacts()
    universe = deepcopy(artifacts["connection_universe"])
    universe["albums"][0]["title"] = "Renamed Elsewhere"
    artifacts["connection_universe"] = universe
    report = public_artifacts_failures(**artifacts)
    assert any("title" in f and "master-1" in f for f in report["connection_guesser"])


def test_connection_universe_artist_rename_is_caught() -> None:
    artifacts = _clean_artifacts()
    universe = deepcopy(artifacts["connection_universe"])
    universe["albums"][1]["act"] = "Someone Else"
    artifacts["connection_universe"] = universe
    report = public_artifacts_failures(**artifacts)
    assert any("artist" in f and "master-2" in f for f in report["connection_guesser"])


def test_routes_pool_built_against_an_older_catalog_is_caught() -> None:
    artifacts = _with_regenerated_catalog(_clean_artifacts())
    report = public_artifacts_failures(**artifacts)
    assert any("catalog_version" in f for f in report["record_routes"])


def test_routes_universe_album_missing_from_catalog_is_caught() -> None:
    artifacts = _clean_artifacts()
    universe = deepcopy(artifacts["routes_universe"])
    universe["albums"][0]["id"] = "master-99"
    artifacts["routes_universe"] = universe
    report = public_artifacts_failures(**artifacts)
    assert any("master-99" in f and "catalog" in f for f in report["record_routes"])


def test_routes_universe_retitled_album_is_caught() -> None:
    artifacts = _clean_artifacts()
    universe = deepcopy(artifacts["routes_universe"])
    universe["albums"][1]["title"] = "Renamed Elsewhere"
    artifacts["routes_universe"] = universe
    report = public_artifacts_failures(**artifacts)
    assert any("title" in f and "master-2" in f for f in report["record_routes"])


def test_challenge_built_against_an_older_catalog_is_caught() -> None:
    artifacts = _with_regenerated_catalog(_clean_artifacts())
    report = public_artifacts_failures(**artifacts)
    assert any("catalog_version" in f for f in report["challenge"])


def test_challenge_without_a_catalog_version_is_caught() -> None:
    """challenge_failures tolerates a missing catalog_version (a hand-written
    query list has no catalog), but the live, catalog-derived challenge.v3 must
    carry one -- otherwise it can never be proven current."""
    artifacts = _clean_artifacts()
    challenge = deepcopy(artifacts["challenge"])
    challenge["provenance"]["catalog_version"] = None
    artifacts["challenge"] = challenge
    report = public_artifacts_failures(**artifacts)
    assert any("catalog_version" in f for f in report["challenge"])


def test_challenge_album_missing_from_catalog_is_caught() -> None:
    artifacts = _clean_artifacts()
    challenge = deepcopy(artifacts["challenge"])
    challenge["albums"][0]["id"] = "master-99"
    artifacts["challenge"] = challenge
    report = public_artifacts_failures(**artifacts)
    assert any("master-99" in f and "catalog" in f for f in report["challenge"])


def test_challenge_covering_fewer_albums_than_the_catalog_is_allowed() -> None:
    """ADR 0067: the album shelf shows the whole catalog; the challenge may
    legitimately cover fewer albums (matching can miss one), so a subset is
    clean. Staleness is caught by catalog_version, not by set equality."""
    artifacts = _clean_artifacts()
    challenge = deepcopy(artifacts["challenge"])
    challenge["albums"] = challenge["albums"][:1]
    artifacts["challenge"] = challenge
    report = public_artifacts_failures(**artifacts)
    assert not any("not in the canonical catalog" in f for f in report["challenge"])


def test_challenge_retitled_album_is_caught() -> None:
    artifacts = _clean_artifacts()
    challenge = deepcopy(artifacts["challenge"])
    challenge["albums"][0]["title"] = "Renamed Elsewhere"
    artifacts["challenge"] = challenge
    report = public_artifacts_failures(**artifacts)
    assert any("title" in f and "master-1" in f for f in report["challenge"])


def test_challenge_artist_rename_is_caught() -> None:
    artifacts = _clean_artifacts()
    challenge = deepcopy(artifacts["challenge"])
    challenge["albums"][1]["artist"] = "Someone Else"
    artifacts["challenge"] = challenge
    report = public_artifacts_failures(**artifacts)
    assert any("artist" in f and "master-2" in f for f in report["challenge"])


def _registry_without_release(artifacts: dict[str, Any], release_id: int) -> dict[str, Any]:
    registry = deepcopy(artifacts["evidence_release_registry"])
    index = registry["release_ids"].index(release_id)
    for key in (
        "release_ids",
        "titles",
        "years",
        "countries",
        "master_ids",
        "source_urls",
        "cover_uri150s",
        "relation_to_catalog_album_ids",
    ):
        del registry[key][index]
    registry["evidence_release_registry_version"] = evidence_release_registry_version(
        registry, _SNAPSHOT
    )
    artifacts = dict(artifacts)
    artifacts["evidence_release_registry"] = registry
    return artifacts


def test_registry_missing_a_release_cited_by_the_challenge_is_caught() -> None:
    artifacts = _registry_without_release(_clean_artifacts(), 1)
    report = public_artifacts_failures(**artifacts)
    assert any("challenge" in f and "1" in f for f in report["evidence_release_registry"])


def test_registry_missing_a_release_cited_by_routes_is_caught() -> None:
    artifacts = _registry_without_release(_clean_artifacts(), 500)
    report = public_artifacts_failures(**artifacts)
    assert any("routes" in f and "500" in f for f in report["evidence_release_registry"])


def test_registry_missing_a_release_cited_by_the_graph_is_caught() -> None:
    artifacts = _clean_artifacts()
    graph = deepcopy(artifacts["pathfinding_graph"])
    graph["evidence_release_ids"][0] = 777
    graph["pathfinding_graph_version"] = pathfinding_graph_version(graph, _SNAPSHOT)
    artifacts["pathfinding_graph"] = graph
    report = public_artifacts_failures(**artifacts)
    assert any("graph" in f and "777" in f for f in report["evidence_release_registry"])


def test_search_index_stale_label_is_caught() -> None:
    artifacts = _clean_artifacts()
    index = deepcopy(artifacts["search_index"])
    entry = next(e for e in index["entries"] if e["id"] == "master-1")
    entry["label"] = "Renamed Elsewhere"
    index["search_index_version"] = search_index_version(index["entries"], _SNAPSHOT)
    artifacts["search_index"] = index
    report = public_artifacts_failures(**artifacts)
    assert any("label" in f and "master-1" in f for f in report["search_index"])


def test_optional_catalog_argument_extends_the_per_artifact_validators() -> None:
    """The fleet's `connection-rounds` / `record-routes` validators call these
    with (universe, rounds) or, now, (universe, rounds, catalog)."""
    from networked_players_contracts import connection_rounds_failures, record_routes_failures

    artifacts = _with_regenerated_catalog(_clean_artifacts())
    catalog = artifacts["catalog"]
    connection = (artifacts["connection_universe"], artifacts["connection_rounds"])
    routes = (artifacts["routes_universe"], artifacts["routes_rounds"])
    assert connection_rounds_failures(*connection) == []
    assert connection_rounds_failures(*connection, catalog)
    assert record_routes_failures(*routes) == []
    assert record_routes_failures(*routes, catalog)
