"""Album-projection clustering study (Campaign Atlas, work package S1 / E1).

Method note: `docs/RESEARCH_ALBUM_PROJECTION_METHOD.md`. Gate being measured:
ADR 0072 section 6. ADR 0070 denied Leiden on the PERFORMER graph because
album anchors are never adjacent; this module measures the untested object --
the ALBUM PROJECTION (records as nodes, an edge when two records share
credited performers).

This module only MEASURES. It never decides the gate: the numeric criteria are
reported as data with pass/fail flags, and the fourth criterion (owner
legibility review) is the constant string "pending". Output contains counts and
graph statistics only -- no elapsed-time or memory figures (ADR 0018).

Reproducible from committed public artifacts alone (`graph.v4.json`,
`albums.v1.json`); no private corpus.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import igraph as ig

from .route_quality import PublishedGraph, load_published_graph

DEFAULT_MIN_SHARED = 2
DEFAULT_RESOLUTION = 2.0
DEFAULT_SEEDS = tuple(range(10))
DEFAULT_NULL_COUNT = 20
DEFAULT_PERTURBATION_REPEATS = 10
DEFAULT_PERTURBATION_FRACTION = 0.10
SWEEP_MIN_SHARED = (1, 2, 3)
SWEEP_RESOLUTIONS = (1.0, 2.0, 3.0)

MAX_LARGEST_CLUSTER_SHARE = 0.25
MIN_COVERAGE = 0.40
MIN_NULL_Z = 3.0
QUALIFYING_MIN_ALBUMS = 4
QUALIFYING_MIN_ARTISTS = 3
TOP_BRIDGE_PLAYERS = 8
# Bounded, not "until stable" (-1): igraph can spin forever on tiny graphs.
LEIDEN_MAX_ITERATIONS = 50
_ROUND = 6


class AlbumProjectionError(ValueError):
    """Raised for malformed inputs."""


# --------------------------------------------------------------------- inputs


def _load_catalog_albums(catalog_path: Path) -> list[dict[str, Any]]:
    catalog = json.loads(Path(catalog_path).read_text())
    albums = catalog.get("albums")
    if not isinstance(albums, list):
        raise AlbumProjectionError("catalog has no 'albums' list")
    out: list[dict[str, Any]] = []
    for album in albums:
        if isinstance(album, dict) and "id" in album:
            out.append(
                {
                    "id": str(album["id"]),
                    "title": album.get("title"),
                    "artist": album.get("artist"),
                    "artist_id": album.get("artist_id"),
                    "year": album.get("year"),
                }
            )
    out.sort(key=lambda a: a["id"])
    return out


def album_performer_sets(
    published: PublishedGraph, album_ids: list[str]
) -> dict[str, frozenset[int]]:
    """Performer set per album = neighbour node indices of its virtual album
    anchor. Albums missing from the graph get an empty set. Other anchors are
    never counted as performers."""
    anchor_indices: set[int] = set()
    for virtual_id in published.virtual_id_by_album_id.values():
        index = published.index_by_node_id.get(virtual_id)
        if index is not None:
            anchor_indices.add(index)
    result: dict[str, frozenset[int]] = {}
    for album_id in album_ids:
        virtual_id = published.virtual_id_by_album_id.get(album_id)
        index = published.index_by_node_id.get(virtual_id) if virtual_id is not None else None
        if index is None:
            result[album_id] = frozenset()
            continue
        result[album_id] = frozenset(
            published.neighbors[slot]
            for slot in published.slots(index)
            if published.neighbors[slot] not in anchor_indices
        )
    return result


# ----------------------------------------------------------------- projection


def build_projection(
    albums: list[dict[str, Any]],
    performers: dict[str, frozenset[int]],
    *,
    min_shared: int = DEFAULT_MIN_SHARED,
    include_same_artist: bool = False,
) -> dict[str, Any]:
    """Weighted album-projection edge list. Nodes are `albums` (in the given
    order). `weight` = sum over shared performers of 1/ln(1 + albums(p)),
    where albums(p) counts ALL catalog albums p is on (Adamic-Adar style hub
    discount)."""
    album_ids = [a["id"] for a in albums]
    artist_of = {a["id"]: a.get("artist_id") for a in albums}
    albums_of_performer: dict[int, list[str]] = defaultdict(list)
    for album_id in album_ids:
        for p in performers.get(album_id, frozenset()):
            albums_of_performer[p].append(album_id)
    shared: dict[tuple[str, str], int] = defaultdict(int)
    weight: dict[tuple[str, str], float] = defaultdict(float)
    for on in albums_of_performer.values():
        if len(on) < 2:
            continue
        discount = 1.0 / math.log(1.0 + len(on))
        for a, b in combinations(sorted(on), 2):
            shared[(a, b)] += 1
            weight[(a, b)] += discount
    edges: list[dict[str, Any]] = []
    for (a, b), count in sorted(shared.items()):
        if count < min_shared:
            continue
        if not include_same_artist and artist_of[a] is not None and artist_of[a] == artist_of[b]:
            continue
        edges.append({"a": a, "b": b, "shared": count, "weight": weight[(a, b)]})
    return {"album_ids": album_ids, "edges": edges}


def _igraph_from_projection(projection: dict[str, Any]) -> ig.Graph:
    index = {album_id: i for i, album_id in enumerate(projection["album_ids"])}
    graph = ig.Graph()
    graph.add_vertices(len(index))
    graph.add_edges([(index[e["a"]], index[e["b"]]) for e in projection["edges"]])
    graph.es["weight"] = [float(e["weight"]) for e in projection["edges"]]
    return graph


# ----------------------------------------------------------------- clustering


def _canonical_membership(membership: list[int]) -> list[int]:
    """Relabel clusters by (size desc, smallest member index) so equal
    partitions have identical labels."""
    members: dict[int, list[int]] = defaultdict(list)
    for node, c in enumerate(membership):
        members[c].append(node)
    order = sorted(members.values(), key=lambda m: (-len(m), m[0]))
    relabel = [0] * len(membership)
    for new, nodes in enumerate(order):
        for node in nodes:
            relabel[node] = new
    return relabel


def _leiden_once(graph: ig.Graph, resolution: float, seed: int) -> list[int]:
    random.seed(seed)
    clustering = graph.community_leiden(
        objective_function="modularity",
        weights="weight",
        resolution=resolution,
        n_iterations=LEIDEN_MAX_ITERATIONS,
    )
    return _canonical_membership(list(clustering.membership))


def _modularity(graph: ig.Graph, membership: list[int], resolution: float = 1.0) -> float:
    if graph.ecount() == 0:
        return 0.0
    return float(graph.modularity(membership, weights="weight", resolution=resolution))


def cluster_runs(
    graph: ig.Graph, resolution: float, seeds: tuple[int, ...] | list[int]
) -> list[list[int]]:
    """One canonical membership per seed (empty graph -> all singletons)."""
    if graph.ecount() == 0:
        return [list(range(graph.vcount())) for _ in seeds]
    return [_leiden_once(graph, resolution, seed) for seed in seeds]


def best_partition(graph: ig.Graph, runs: list[list[int]], resolution: float) -> list[int]:
    """Best partition by the modularity at the study's own resolution (the
    quantity Leiden optimised); ties broken by the lexicographically smallest
    canonical membership, so the choice never depends on run order."""
    scored = [(-round(_modularity(graph, m, resolution), 10), m) for m in runs]
    return min(scored, key=lambda s: (s[0], s[1]))[1]


def _ari(a: list[int], b: list[int]) -> float:
    """Adjusted Rand index (Hubert-Arabie) from contingency counts."""
    n = len(a)
    if n < 2:
        return 1.0

    def comb2(x: int) -> float:
        return x * (x - 1) / 2.0

    cells: dict[tuple[int, int], int] = defaultdict(int)
    rows: dict[int, int] = defaultdict(int)
    cols: dict[int, int] = defaultdict(int)
    for x, y in zip(a, b, strict=True):
        cells[(x, y)] += 1
        rows[x] += 1
        cols[y] += 1
    index = sum(comb2(v) for v in cells.values())
    sum_rows = sum(comb2(v) for v in rows.values())
    sum_cols = sum(comb2(v) for v in cols.values())
    total = comb2(n)
    expected = sum_rows * sum_cols / total
    maximum = (sum_rows + sum_cols) / 2.0
    if maximum == expected:
        return 1.0
    return (index - expected) / (maximum - expected)


# ---------------------------------------------------------------- measurement


def _clusters_of(membership: list[int]) -> list[list[int]]:
    groups: dict[int, list[int]] = defaultdict(list)
    for node, c in enumerate(membership):
        groups[c].append(node)
    return [groups[c] for c in sorted(groups)]


def _stability(
    graph: ig.Graph,
    runs: list[list[int]],
    reference: list[int],
    *,
    resolution: float,
    seeds: tuple[int, ...] | list[int],
    repeats: int,
    fraction: float,
) -> dict[str, Any]:
    pair_ari = [_ari(a, b) for a, b in combinations(runs, 2)]
    out: dict[str, Any] = {
        "seed_run_count": len(runs),
        "seed_ari_mean": round(statistics.fmean(pair_ari), _ROUND) if pair_ari else None,
        "seed_ari_min": round(min(pair_ari), _ROUND) if pair_ari else None,
        "perturbation_fraction": fraction,
        "perturbation_repeats": repeats,
    }
    edge_count = graph.ecount()
    drop = round(edge_count * fraction)
    if edge_count == 0 or drop == 0 or repeats <= 0:
        out["perturbation_ari_mean"] = None
        out["perturbation_ari_min"] = None
        return out
    scores: list[float] = []
    for r in range(repeats):
        rng = random.Random(10_000 + r)
        dropped = set(rng.sample(range(edge_count), drop))
        kept = [e for e in range(edge_count) if e not in dropped]
        sub = graph.subgraph_edges(kept, delete_vertices=False)
        retained = [v for v in range(sub.vcount()) if sub.degree(v) > 0 and graph.degree(v) > 0]
        if len(retained) < 2:
            continue
        sub_runs = cluster_runs(sub, resolution, seeds)
        sub_best = best_partition(sub, sub_runs, resolution)
        scores.append(_ari([reference[v] for v in retained], [sub_best[v] for v in retained]))
    out["perturbation_ari_mean"] = round(statistics.fmean(scores), _ROUND) if scores else None
    out["perturbation_ari_min"] = round(min(scores), _ROUND) if scores else None
    return out


def _null_model(
    graph: ig.Graph,
    *,
    resolution: float,
    seeds: tuple[int, ...] | list[int],
    null_count: int,
    real_q: float,
) -> dict[str, Any]:
    qs: list[float] = []
    if graph.ecount() >= 2:
        weights = list(graph.es["weight"])
        for i in range(null_count):
            rng = random.Random(20_000 + i)
            null = graph.copy()
            random.seed(20_000 + i)
            null.rewire(n=max(10 * null.ecount(), 10), mode="simple")
            permuted = weights[:]
            rng.shuffle(permuted)
            null.es["weight"] = permuted
            runs = cluster_runs(null, resolution, seeds)
            qs.append(_modularity(null, best_partition(null, runs, resolution)))
    mean = statistics.fmean(qs) if qs else None
    std = statistics.pstdev(qs) if len(qs) > 1 else None
    z = (real_q - mean) / std if (mean is not None and std) else None
    return {
        "null_count": len(qs),
        "null_q_mean": round(mean, _ROUND) if mean is not None else None,
        "null_q_std": round(std, _ROUND) if std is not None else None,
        "z_score": round(z, 4) if z is not None else None,
    }


def _rewire_incidence(
    albums: list[dict[str, Any]], performers: dict[str, frozenset[int]], rng: random.Random
) -> dict[str, frozenset[int]]:
    """Degree-preserving rewiring of the album-performer INCIDENCE (bipartite)
    graph: every album keeps its performer count and every performer keeps
    its album count. Double-edge swaps (a,p),(b,q) -> (a,q),(b,p), rejected
    if they would duplicate an existing incidence."""
    incidence = [(a["id"], p) for a in albums for p in sorted(performers.get(a["id"], ()))]
    present = set(incidence)
    if len(incidence) >= 2:
        for _ in range(10 * len(incidence)):
            i, j = rng.randrange(len(incidence)), rng.randrange(len(incidence))
            (a, p), (b, q) = incidence[i], incidence[j]
            if a == b or p == q or (a, q) in present or (b, p) in present:
                continue
            present -= {(a, p), (b, q)}
            present |= {(a, q), (b, p)}
            incidence[i], incidence[j] = (a, q), (b, p)
    rebuilt: dict[str, set[int]] = {a["id"]: set() for a in albums}
    for album_id, p in incidence:
        rebuilt[album_id].add(p)
    return {k: frozenset(v) for k, v in rebuilt.items()}


def _bipartite_null_model(
    albums: list[dict[str, Any]],
    performers: dict[str, frozenset[int]],
    *,
    min_shared: int,
    include_same_artist: bool,
    resolution: float,
    seeds: tuple[int, ...] | list[int],
    null_count: int,
    real_q: float,
    real_edge_count: int,
) -> dict[str, Any]:
    """Stricter null: rewire the album-performer incidence, RE-PROJECT with the
    same parameters, and cluster with the same procedure. Unlike rewiring the
    projection itself, this keeps the clique-rich structure that ANY
    bipartite projection has (a performer on k albums yields a k-clique), so
    it asks whether the real data is more clustered than random sharing with
    the same album sizes and performer fame."""
    qs: list[float] = []
    if real_edge_count > 0:
        for i in range(null_count):
            rng = random.Random(30_000 + i)
            null_projection = build_projection(
                albums,
                _rewire_incidence(albums, performers, rng),
                min_shared=min_shared,
                include_same_artist=include_same_artist,
            )
            null = _igraph_from_projection(null_projection)
            runs = cluster_runs(null, resolution, seeds)
            qs.append(_modularity(null, best_partition(null, runs, resolution)))
    mean = statistics.fmean(qs) if qs else None
    std = statistics.pstdev(qs) if len(qs) > 1 else None
    z = (real_q - mean) / std if (mean is not None and std) else None
    return {
        "null_count": len(qs),
        "null_q_mean": round(mean, _ROUND) if mean is not None else None,
        "null_q_std": round(std, _ROUND) if std is not None else None,
        "z_score": round(z, 4) if z is not None else None,
    }


def _share(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, _ROUND) if denominator else None


def _cluster_detail(
    nodes: list[int],
    albums: list[dict[str, Any]],
    performers: dict[str, frozenset[int]],
    published: PublishedGraph | None,
    edge_pairs: set[tuple[int, int]],
) -> dict[str, Any]:
    members = [albums[i] for i in nodes]
    members_sorted = sorted(members, key=lambda a: (a["year"] is None, a["year"] or 0, a["id"]))
    years = [a["year"] for a in members if isinstance(a["year"], int)]
    node_set = set(nodes)
    internal = sum(1 for a, b in edge_pairs if a in node_set and b in node_set)
    possible = len(nodes) * (len(nodes) - 1) // 2
    counts: dict[int, int] = defaultdict(int)
    for a in members:
        for p in performers.get(a["id"], frozenset()):
            counts[p] += 1
    ranked = sorted(
        ((p, c) for p, c in counts.items() if c >= 2),
        key=lambda pc: (-pc[1], published.names[pc[0]] if published else "", pc[0]),
    )
    return {
        "album_count": len(nodes),
        "artist_count": len({a["artist_id"] for a in members}),
        "albums": [
            {
                "id": a["id"],
                "title": a["title"],
                "artist": a["artist"],
                "year": a["year"],
            }
            for a in members_sorted
        ],
        "internal_edge_count": internal,
        "internal_density": round(internal / possible, _ROUND) if possible else None,
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "year_span": (max(years) - min(years)) if years else None,
        "bridge_players": [
            {"name": published.names[p] if published else str(p), "album_count": c}
            for p, c in ranked[:TOP_BRIDGE_PLAYERS]
        ],
    }


def measure_projection(
    albums: list[dict[str, Any]],
    performers: dict[str, frozenset[int]],
    published: PublishedGraph | None = None,
    *,
    min_shared: int = DEFAULT_MIN_SHARED,
    include_same_artist: bool = False,
    resolution: float = DEFAULT_RESOLUTION,
    seeds: tuple[int, ...] | list[int] = DEFAULT_SEEDS,
    null_count: int = DEFAULT_NULL_COUNT,
    perturbation_repeats: int = DEFAULT_PERTURBATION_REPEATS,
    perturbation_fraction: float = DEFAULT_PERTURBATION_FRACTION,
    detail: bool = True,
) -> dict[str, Any]:
    """Run the whole measurement for one parameter set. Deterministic for a
    fixed argument list (every random choice is seeded)."""
    projection = build_projection(
        albums, performers, min_shared=min_shared, include_same_artist=include_same_artist
    )
    graph = _igraph_from_projection(projection)
    n = graph.vcount()
    runs = cluster_runs(graph, resolution, seeds)
    membership = best_partition(graph, runs, resolution) if runs else list(range(n))
    clusters = _clusters_of(membership)
    clusters.sort(key=lambda c: (-len(c), c[0]))
    sizes = [len(c) for c in clusters]
    artist_ids = [a["artist_id"] for a in albums]

    qualifying = [
        c
        for c in clusters
        if len(c) >= QUALIFYING_MIN_ALBUMS
        and len({artist_ids[i] for i in c}) >= QUALIFYING_MIN_ARTISTS
    ]
    covered = sum(len(c) for c in qualifying)
    largest = sizes[0] if sizes else 0
    q = _modularity(graph, membership)
    null = _null_model(graph, resolution=resolution, seeds=seeds, null_count=null_count, real_q=q)
    bipartite_null = _bipartite_null_model(
        albums,
        performers,
        min_shared=min_shared,
        include_same_artist=include_same_artist,
        resolution=resolution,
        seeds=seeds,
        null_count=null_count,
        real_q=q,
        real_edge_count=graph.ecount(),
    )
    stability = _stability(
        graph,
        runs,
        membership,
        resolution=resolution,
        seeds=seeds,
        repeats=perturbation_repeats,
        fraction=perturbation_fraction,
    )

    largest_share = _share(largest, n)
    coverage = _share(covered, n)
    z = null["z_score"]
    bipartite_z = bipartite_null["z_score"]
    gate = {
        "criteria": [
            {
                "name": "largest_cluster_share",
                "rule": "<=",
                "threshold": MAX_LARGEST_CLUSTER_SHARE,
                "measured": largest_share,
                "pass": largest_share is not None and largest_share <= MAX_LARGEST_CLUSTER_SHARE,
            },
            {
                "name": "coverage",
                "rule": ">=",
                "threshold": MIN_COVERAGE,
                "measured": coverage,
                "pass": coverage is not None and coverage >= MIN_COVERAGE,
            },
            {
                "name": "modularity_above_null_z",
                "rule": ">=",
                "threshold": MIN_NULL_Z,
                "measured": z,
                "pass": z is not None and z >= MIN_NULL_Z,
                "note": (
                    "Null = the projection graph rewired (degree sequence kept, weights "
                    "permuted), as specified. ADR 0072 says 'clearly above a degree-preserving "
                    "null'; z >= 3 is this study's operationalisation of 'clearly above', not "
                    "an ADR-stated number. CAUTION: this null destroys the clique structure "
                    "every bipartite projection has, so structureless sharing can also pass it "
                    "(see the next criterion)."
                ),
            },
            {
                "name": "modularity_above_bipartite_null_z",
                "rule": ">=",
                "threshold": MIN_NULL_Z,
                "measured": bipartite_z,
                "pass": bipartite_z is not None and bipartite_z >= MIN_NULL_Z,
                "note": (
                    "Stricter, additional null: the album-performer incidence rewired "
                    "(album sizes and performer album-counts kept) and re-projected. Added "
                    "because the projection-rewiring null is biased towards passing."
                ),
            },
        ],
        "owner_legibility_review": "pending",
    }

    edge_pairs = {(min(i, j), max(i, j)) for i, j in (e.tuple for e in graph.es)}
    result: dict[str, Any] = {
        "kind": "album_projection_study",
        "parameters": {
            "min_shared": min_shared,
            "include_same_artist": include_same_artist,
            "resolution": resolution,
            "seeds": list(seeds),
            "null_count": null_count,
            "perturbation_repeats": perturbation_repeats,
            "perturbation_fraction": perturbation_fraction,
            "weight": "sum over shared performers of 1/ln(1+albums(p))",
            "objective": "modularity (Leiden, weighted)",
        },
        "projection": {
            "album_count": n,
            "albums_without_performers": sum(1 for a in albums if not performers.get(a["id"])),
            "edge_count": graph.ecount(),
            "albums_with_an_edge": sum(1 for v in range(n) if graph.degree(v) > 0),
        },
        "clustering": {
            "cluster_count": len(clusters),
            "non_singleton_cluster_count": sum(1 for s in sizes if s > 1),
            "size_distribution": sizes,
            "largest_cluster_size": largest,
            "largest_cluster_share": largest_share,
            "qualifying_cluster_count": len(qualifying),
            "albums_in_qualifying_clusters": covered,
            "coverage": coverage,
            "modularity_q": round(q, _ROUND),
            "modularity_resolution_for_q": 1.0,
        },
        "null_model": null,
        "bipartite_null_model": bipartite_null,
        "stability": stability,
        "gate": gate,
    }
    if detail:
        result["qualifying_clusters"] = [
            _cluster_detail(c, albums, performers, published, edge_pairs) for c in qualifying
        ]
    return result


def run_study(
    graph_path: Path,
    catalog_path: Path,
    *,
    min_shared: int = DEFAULT_MIN_SHARED,
    include_same_artist: bool = False,
    resolution: float = DEFAULT_RESOLUTION,
    seeds: tuple[int, ...] | list[int] = DEFAULT_SEEDS,
    null_count: int = DEFAULT_NULL_COUNT,
    perturbation_repeats: int = DEFAULT_PERTURBATION_REPEATS,
) -> dict[str, Any]:
    published = load_published_graph(graph_path)
    albums = _load_catalog_albums(catalog_path)
    performers = album_performer_sets(published, [a["id"] for a in albums])
    result = measure_projection(
        albums,
        performers,
        published,
        min_shared=min_shared,
        include_same_artist=include_same_artist,
        resolution=resolution,
        seeds=seeds,
        null_count=null_count,
        perturbation_repeats=perturbation_repeats,
    )
    result["inputs"] = {
        "graph": Path(graph_path).name,
        "catalog": Path(catalog_path).name,
        "catalog_album_count": len(albums),
    }
    return result


def run_sweep(
    graph_path: Path,
    catalog_path: Path,
    *,
    include_same_artist: bool = False,
    seeds: tuple[int, ...] | list[int] = DEFAULT_SEEDS,
    null_count: int = DEFAULT_NULL_COUNT,
    perturbation_repeats: int = DEFAULT_PERTURBATION_REPEATS,
) -> dict[str, Any]:
    published = load_published_graph(graph_path)
    albums = _load_catalog_albums(catalog_path)
    performers = album_performer_sets(published, [a["id"] for a in albums])
    rows: list[dict[str, Any]] = []
    for min_shared in SWEEP_MIN_SHARED:
        for resolution in SWEEP_RESOLUTIONS:
            r = measure_projection(
                albums,
                performers,
                published,
                min_shared=min_shared,
                include_same_artist=include_same_artist,
                resolution=resolution,
                seeds=seeds,
                null_count=null_count,
                perturbation_repeats=perturbation_repeats,
                detail=False,
            )
            crit = {c["name"]: c for c in r["gate"]["criteria"]}
            rows.append(
                {
                    "min_shared": min_shared,
                    "resolution": resolution,
                    "edge_count": r["projection"]["edge_count"],
                    "cluster_count": r["clustering"]["cluster_count"],
                    "qualifying_cluster_count": r["clustering"]["qualifying_cluster_count"],
                    "largest_cluster_share": r["clustering"]["largest_cluster_share"],
                    "coverage": r["clustering"]["coverage"],
                    "modularity_q": r["clustering"]["modularity_q"],
                    "null_q_mean": r["null_model"]["null_q_mean"],
                    "z_score": r["null_model"]["z_score"],
                    "bipartite_z_score": r["bipartite_null_model"]["z_score"],
                    "seed_ari_mean": r["stability"]["seed_ari_mean"],
                    "perturbation_ari_mean": r["stability"]["perturbation_ari_mean"],
                    "pass_largest_cluster": crit["largest_cluster_share"]["pass"],
                    "pass_coverage": crit["coverage"]["pass"],
                    "pass_null_z": crit["modularity_above_null_z"]["pass"],
                    "pass_bipartite_null_z": crit["modularity_above_bipartite_null_z"]["pass"],
                }
            )
    return {
        "kind": "album_projection_sweep",
        "parameters": {
            "min_shared": list(SWEEP_MIN_SHARED),
            "resolution": list(SWEEP_RESOLUTIONS),
            "include_same_artist": include_same_artist,
            "seeds": list(seeds),
            "null_count": null_count,
            "perturbation_repeats": perturbation_repeats,
        },
        "owner_legibility_review": "pending",
        "rows": rows,
    }


# ------------------------------------------------------------------- rendering


def _fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def render_markdown(result: dict[str, Any]) -> str:
    p = result["parameters"]
    c = result["clustering"]
    lines = [
        "# Album projection study (measurement only)",
        "",
        f"Parameters: min_shared={p['min_shared']}, include_same_artist="
        f"{p['include_same_artist']}, resolution={p['resolution']}, seeds={len(p['seeds'])}, "
        f"null_count={p['null_count']}.",
        "",
        f"- Albums: {result['projection']['album_count']}; projection edges: "
        f"{result['projection']['edge_count']}; clusters: {c['cluster_count']} "
        f"({c['non_singleton_cluster_count']} with more than one album).",
        f"- Largest cluster share: {_fmt(c['largest_cluster_share'])}; coverage: "
        f"{_fmt(c['coverage'])}; modularity Q (resolution 1): {c['modularity_q']}.",
        f"- Null: mean {_fmt(result['null_model']['null_q_mean'])}, std "
        f"{_fmt(result['null_model']['null_q_std'])}, z {_fmt(result['null_model']['z_score'])}.",
        f"- Bipartite null: mean {_fmt(result['bipartite_null_model']['null_q_mean'])}, std "
        f"{_fmt(result['bipartite_null_model']['null_q_std'])}, z "
        f"{_fmt(result['bipartite_null_model']['z_score'])}.",
        f"- Stability: seed ARI mean {_fmt(result['stability']['seed_ari_mean'])} / min "
        f"{_fmt(result['stability']['seed_ari_min'])}; perturbation ARI mean "
        f"{_fmt(result['stability']['perturbation_ari_mean'])} / min "
        f"{_fmt(result['stability']['perturbation_ari_min'])}.",
        "",
        "## Gate (data only; nothing is decided here)",
        "",
        "| criterion | rule | threshold | measured | pass |",
        "| --- | --- | --- | --- | --- |",
    ]
    for crit in result["gate"]["criteria"]:
        lines.append(
            f"| {crit['name']} | {crit['rule']} | {crit['threshold']} | "
            f"{_fmt(crit['measured'])} | {crit['pass']} |"
        )
    lines += [
        f"| owner_legibility_review | human | 7 of 10 clusters | "
        f"{result['gate']['owner_legibility_review']} | pending |",
        "",
        "## Qualifying clusters (for the legibility review)",
        "",
    ]
    for i, cluster in enumerate(result.get("qualifying_clusters", []), start=1):
        lines.append(
            f"### Cluster {i}: {cluster['album_count']} albums, "
            f"{cluster['artist_count']} artists, years {_fmt(cluster['year_min'])}-"
            f"{_fmt(cluster['year_max'])}, density {_fmt(cluster['internal_density'])}"
        )
        lines.append("")
        for a in cluster["albums"]:
            lines.append(f"- {_fmt(a['year'])} - {a['artist']} - {a['title']}")
        bridges = ", ".join(f"{b['name']} ({b['album_count']})" for b in cluster["bridge_players"])
        lines += ["", f"Bridge players: {bridges or 'none'}", ""]
    return "\n".join(lines).rstrip() + "\n"


def render_sweep_markdown(sweep: dict[str, Any]) -> str:
    lines = [
        "# Album projection sensitivity sweep (measurement only)",
        "",
        "| min_shared | resolution | edges | clusters | qualifying | largest | coverage | Q | "
        "null Q | z | bip. z | seed ARI | perturb ARI | largest ok | coverage ok | z ok | "
        "bip. z ok |",
        "| " + " | ".join(["---"] * 17) + " |",
    ]
    for r in sweep["rows"]:
        lines.append(
            "| "
            + " | ".join(
                _fmt(r[k])
                for k in (
                    "min_shared",
                    "resolution",
                    "edge_count",
                    "cluster_count",
                    "qualifying_cluster_count",
                    "largest_cluster_share",
                    "coverage",
                    "modularity_q",
                    "null_q_mean",
                    "z_score",
                    "bipartite_z_score",
                    "seed_ari_mean",
                    "perturbation_ari_mean",
                    "pass_largest_cluster",
                    "pass_coverage",
                    "pass_null_z",
                    "pass_bipartite_null_z",
                )
            )
            + " |"
        )
    lines += ["", "Owner legibility review: pending (human judgement; never computed).", ""]
    return "\n".join(lines)


def is_under_public_artifacts(path: Path) -> bool:
    """True if the resolved path sits under any `apps/web/public/` directory
    (research outputs must never land in the publication tree, ADR 0054)."""
    parts = Path(path).resolve().parts
    return any(parts[i : i + 3] == ("apps", "web", "public") for i in range(len(parts) - 2))


def dumps(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=True) + "\n"
