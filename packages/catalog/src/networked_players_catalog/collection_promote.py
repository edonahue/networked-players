"""`promote-collection`: the human-approved bridge from a private review
selection to a public Collection artifact (ADR 0074, Campaign Atlas S2).

Operator-run only. It never runs automatically, never reads `data/private/`
by itself (the caller names the files), and by default writes to a staging
directory under `local/`. Publishing into `apps/web/public/data/` happens only
with the explicit `--publish-to`, and publishing is still a separate, owner-
reviewed commit (`docs/REVIEW_PACKET.md`, "Publishing a Collection").

Inputs:

- the private `collection-selection.private.json` the review packet's
  collection mode exports, and the study JSON it was built from (the
  selection's `input_hash` must equal the hash of that study's packet data, so
  a selection cannot be paired with a different study);
- the committed catalog and `graph.v4.json`;
- the owner-written public text: title, intro and optional attribution. These
  are never generated, and the selection's working title and notes are never
  copied (see `_assert_no_private_text`).

Routing: there is no Python mirror of the site's ranked recommended route
(`apps/web/src/game/recommendedRoute.ts`, ADR 0059; `packages/research`'s
`route_quality.py` measures and enumerates but does not rank, and the catalog
package does not depend on research). The builder therefore finds a plain
shortest path on the CSR, first discovered in CSR node order, over real
performer nodes only. That is documented as `route_policy`, is not the site's
ranked route, and is checked on validation as a real path with the graph's own
evidence ids -- not as the best route.
"""

from __future__ import annotations

import itertools
import json
from collections import deque
from pathlib import Path
from typing import Any

from networked_players_contracts.collection import (
    MAX_BRIDGE_PLAYERS,
    MAX_VIA,
    MIN_BRIDGE_RECORDS,
    PLAYABLE_COHORT_V2_SCHEMA_VERSION,
    ROUTE_POLICY,
    GraphIndex,
    collection_artifact_path,
    collection_failures,
    collection_version,
    collections_failures,
    dumps_stable,
    private_field_failures,
)

from .review_packet import build_collection_data, input_hash

SELECTION_KIND = "collection-selection"
DEFAULT_STAGING_DIR = Path("local/collections-staging")
_MIN_PRIVATE_TEXT = 4


class CollectionPromotionError(ValueError):
    """The selection or inputs cannot become a public Collection. The message
    names every failure."""


# ---------------------------------------------------------------- selection


def select_cluster(selection: Any, study: Any, cluster: int | None) -> dict[str, Any]:
    """Validate the private selection against its study and return the chosen
    kept cluster as `{"records": [...], "working_title": str, "note": str}`.
    Reads the private fields only to guard against leaking them."""
    if not isinstance(selection, dict) or selection.get("kind") != SELECTION_KIND:
        raise CollectionPromotionError(f"selection must be a {SELECTION_KIND!r} export")
    if selection.get("private") is not True:
        raise CollectionPromotionError("selection is not marked private; refusing to use it")
    try:
        study_hash = input_hash(build_collection_data(study))
    except Exception as exc:  # study shape errors surface as one clear message
        raise CollectionPromotionError(f"study JSON is not usable: {exc}") from exc
    if selection.get("input_hash") != study_hash:
        raise CollectionPromotionError(
            "selection was not exported from this study (input_hash differs)"
        )
    entries = selection.get("clusters")
    if not isinstance(entries, list):
        raise CollectionPromotionError("selection has no 'clusters' list")
    if cluster is None:
        kept = [e["cluster"] for e in entries if isinstance(e, dict) and e.get("status") == "keep"]
        if len(kept) != 1:
            raise CollectionPromotionError(
                f"--cluster is required: {len(kept)} clusters are marked keep ({kept})"
            )
        cluster = kept[0]
    chosen = next((e for e in entries if isinstance(e, dict) and e.get("cluster") == cluster), None)
    if chosen is None:
        raise CollectionPromotionError(f"selection has no cluster {cluster}")
    if chosen.get("status") != "keep":
        raise CollectionPromotionError(
            f"cluster {cluster} has status {chosen.get('status')!r}; only 'keep' can be promoted"
        )
    study_albums = {
        a["id"]
        for c in build_collection_data(study)["clusters"]
        if c["index"] == cluster
        for a in c["albums"]
    }
    records: list[str] = []
    for record in chosen.get("kept_records") or []:
        record_id = record.get("id") if isinstance(record, dict) else None
        if not isinstance(record_id, str) or record_id not in study_albums:
            raise CollectionPromotionError(
                f"kept record {record_id!r} is not in the study's cluster {cluster}"
            )
        if record_id in records:
            raise CollectionPromotionError(f"kept record {record_id!r} is listed twice")
        records.append(record_id)
    return {
        "records": records,
        "working_title": str(chosen.get("working_title") or ""),
        "note": str(chosen.get("note") or ""),
    }


# ------------------------------------------------------------------- routes


def _route_tree(gi: GraphIndex, source: str, targets: list[str]) -> dict[str, list[int]]:
    """Shortest routes from `source` to each target, as lists of performer
    node ids. One bounded BFS over real nodes (anchors are never entered, so a
    route cannot pass through another album's anchor); ties go to whichever
    node the BFS discovered first, in CSR order."""
    anchor = gi.anchor_index(source)
    if anchor is None:
        return {}
    parent: dict[int, int] = {}
    depth: dict[int, int] = {}
    queue: deque[int] = deque()
    for slot in gi.slots(anchor):
        n = gi.neighbors[slot]
        if gi.node_ids[n] > 0 and n not in parent:
            parent[n] = -1
            depth[n] = 1
            queue.append(n)
    while queue:
        current = queue.popleft()
        if depth[current] >= MAX_VIA:
            continue
        for slot in gi.slots(current):
            n = gi.neighbors[slot]
            if gi.node_ids[n] > 0 and n not in parent:
                parent[n] = current
                depth[n] = depth[current] + 1
                queue.append(n)
    rank = {n: i for i, n in enumerate(parent)}  # dict order == discovery order
    routes: dict[str, list[int]] = {}
    for target in targets:
        reached = [n for n in gi.performer_indices(target) if n in rank]
        if not reached:
            continue
        end = min(reached, key=lambda n: rank[n])
        chain: list[int] = []
        node = end
        while node != -1:
            chain.append(gi.node_ids[node])
            node = parent[node]
        routes[target] = chain[::-1]
    return routes


def _route_fields(gi: GraphIndex, via: list[int]) -> dict[str, Any]:
    evidence = []
    for a, b in itertools.pairwise(via):
        release = gi.edge_evidence(a, b)
        if release is None:  # cannot happen for a BFS path; fail loudly if it does
            raise CollectionPromotionError(f"internal: no edge between {a} and {b}")
        evidence.append(release)
    return {
        "via": via,
        "via_names": [gi.names[gi.index_by_id[v]] for v in via],
        "evidence_release_ids": evidence,
    }


def bridge_players(gi: GraphIndex, records: list[str]) -> list[dict[str, Any]]:
    """Performers adjacent to the anchors of at least MIN_BRIDGE_RECORDS of the
    records, most-connected first (ties by artist id), at most
    MAX_BRIDGE_PLAYERS."""
    on: dict[int, list[str]] = {}
    for record in records:
        for n in gi.performer_indices(record):
            on.setdefault(gi.node_ids[n], []).append(record)
    ranked = sorted(
        (item for item in on.items() if len(item[1]) >= MIN_BRIDGE_RECORDS),
        key=lambda item: (-len(item[1]), item[0]),
    )
    return [
        {"artist_id": artist_id, "name": gi.names[gi.index_by_id[artist_id]], "records": rec}
        for artist_id, rec in ranked[:MAX_BRIDGE_PLAYERS]
    ]


# -------------------------------------------------------------------- build


def build_collection(
    *,
    records: list[str],
    catalog: dict[str, Any],
    graph: dict[str, Any],
    collection_id: str,
    title: str,
    intro: str,
    generated_at: str,
    attribution: dict[str, str] | None = None,
    journey: list[str] | None = None,
    playable: bool = True,
) -> dict[str, Any]:
    """Assemble and validate the public artifact. Every field is written
    explicitly; nothing from the private selection is copied by reference."""
    problems = GraphIndex.shape_failures(graph)
    if problems:
        raise CollectionPromotionError("; ".join(problems))
    gi = GraphIndex(graph)
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "collection_id": collection_id,
        "title": title,
        "intro": intro,
        "generated_at": generated_at,
        "records": list(records),
        "bridge_players": bridge_players(gi, records),
    }
    if attribution is not None:
        artifact["attribution"] = {
            "label": attribution.get("label", ""),
            "source_url": attribution.get("source_url", ""),
        }
    if journey:
        artifact["journey"] = _journey(gi, records, journey)
    if playable:
        artifact["playable_cohort"] = _playable(gi, records)
    artifact["provenance"] = {
        "inputs": {
            "catalog": catalog.get("catalog_version"),
            "pathfinding_graph": graph.get("pathfinding_graph_version"),
        },
        "collection_version": "",
    }
    artifact["provenance"]["collection_version"] = collection_version(artifact)
    failures = collection_failures(artifact, catalog, graph)
    if failures:
        raise CollectionPromotionError(
            "the collection fails its contract:\n- " + "\n- ".join(failures)
        )
    return artifact


def _journey(gi: GraphIndex, records: list[str], order: list[str]) -> list[dict[str, Any]]:
    if len(order) < 2:
        raise CollectionPromotionError("--journey needs at least two record ids")
    unknown = [r for r in order if r not in records]
    if unknown:
        raise CollectionPromotionError(f"journey records not in the collection: {unknown}")
    if len(set(order)) != len(order):
        raise CollectionPromotionError("journey must not revisit a record")
    hops: list[dict[str, Any]] = []
    for a, b in itertools.pairwise(order):
        via = _route_tree(gi, a, [b]).get(b)
        if via is None:
            raise CollectionPromotionError(
                f"journey hop {a} -> {b}: no route of at most {MAX_VIA} performers in the graph"
            )
        hops.append({"from_record": a, "to_record": b, **_route_fields(gi, via)})
    return hops


def _playable(gi: GraphIndex, records: list[str]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(records):
        routes = _route_tree(gi, a, records[i + 1 :])
        for b in records[i + 1 :]:
            via = routes.get(b)
            if via is not None:
                pairs.append(
                    {
                        "record_a": a,
                        "record_b": b,
                        "hop_count": len(via) - 1,
                        **_route_fields(gi, via),
                    }
                )
    return {
        "schema_version": PLAYABLE_COHORT_V2_SCHEMA_VERSION,
        "route_policy": ROUTE_POLICY,
        "pairs": pairs,
    }


def _assert_no_private_text(
    artifact: dict[str, Any], *, working_title: str, note: str, title: str
) -> None:
    """Belt and braces on top of the explicit field-by-field construction: the
    selection's note and working title must not surface anywhere in the output.
    A working title becomes public only by being passed as `--title`."""
    problems = private_field_failures(artifact)
    text = json.dumps(artifact, ensure_ascii=False)
    for label, private in (("note", note), ("working title", working_title)):
        if len(private) >= _MIN_PRIVATE_TEXT and private != title and private in text:
            problems.append(f"the selection's {label} text appears in the public artifact")
    if problems:
        raise CollectionPromotionError("; ".join(problems))


# ---------------------------------------------------------------------- IO


def _refuse_public_path(path: Path) -> None:
    parts = path.resolve().parts
    if any(parts[i : i + 3] == ("apps", "web", "public") for i in range(len(parts) - 2)):
        raise CollectionPromotionError(
            f"refusing to stage under apps/web/public/: {path} (use --publish-to, explicitly)"
        )


def write_collection(
    directory: Path,
    artifact: dict[str, Any],
    *,
    catalog: dict[str, Any],
    graph: dict[str, Any],
) -> list[Path]:
    """Write `<id>.v1.json` and merge the entry into `index.v1.json` in
    `directory`, then validate the resulting directory as a whole."""
    directory.mkdir(parents=True, exist_ok=True)
    cid = artifact["collection_id"]
    index_path = directory / "index.v1.json"
    index: dict[str, Any] = (
        json.loads(index_path.read_text())
        if index_path.is_file()
        else {"schema_version": 1, "collections": []}
    )
    entries = [e for e in index["collections"] if e.get("collection_id") != cid]
    entries.append(
        {
            "collection_id": cid,
            "title": artifact["title"],
            "artifact_path": collection_artifact_path(cid),
            "record_count": len(artifact["records"]),
            "collection_version": artifact["provenance"]["collection_version"],
        }
    )
    index["collections"] = sorted(entries, key=lambda e: e["collection_id"])
    files: dict[str, Any] = {}
    for path in sorted(directory.glob("*.v1.json")):
        if path.name not in ("index.v1.json", f"{cid}.v1.json"):
            files[path.name.removesuffix(".v1.json")] = json.loads(path.read_text())
    files[cid] = artifact
    failures = collections_failures({"index": index, "files": files}, catalog, graph)
    if failures:
        raise CollectionPromotionError(
            "the resulting collections directory fails validation:\n- " + "\n- ".join(failures)
        )
    artifact_path = directory / f"{cid}.v1.json"
    artifact_path.write_text(dumps_stable(artifact))
    index_path.write_text(dumps_stable(index))
    return [artifact_path, index_path]


def load_public_text(path: Path) -> dict[str, Any]:
    """The owner-written public text: `{"title", "intro", "attribution"?}`."""
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not set(payload) <= {"title", "intro", "attribution"}:
        raise CollectionPromotionError(
            "--text-file must be a JSON object with only title, intro and optional attribution"
        )
    problems = private_field_failures(payload)
    if problems:
        raise CollectionPromotionError("; ".join(problems))
    return payload


def run_promote_collection(args: Any) -> int:
    import sys

    try:
        text: dict[str, Any] = load_public_text(args.text_file) if args.text_file else {}
        title = args.title if args.title is not None else text.get("title", "")
        intro = args.intro if args.intro is not None else text.get("intro", "")
        selection = json.loads(args.selection.read_text())
        study = json.loads(args.study.read_text())
        catalog = json.loads(args.catalog.read_text())
        graph = json.loads(args.graph.read_text())
        chosen = select_cluster(selection, study, args.cluster)
        artifact = build_collection(
            records=chosen["records"],
            catalog=catalog,
            graph=graph,
            collection_id=args.collection_id,
            title=title,
            intro=intro,
            generated_at=args.generated_at,
            attribution=text.get("attribution"),
            journey=[r for r in args.journey.split(",") if r] if args.journey else None,
            playable=not args.skip_playable,
        )
        _assert_no_private_text(
            artifact,
            working_title=chosen["working_title"],
            note=chosen["note"],
            title=title,
        )
        if args.publish_to is not None:
            target = args.publish_to / "collections"
        else:
            _refuse_public_path(args.output_dir)
            target = args.output_dir
        written = write_collection(target, artifact, catalog=catalog, graph=graph)
    except (CollectionPromotionError, OSError, ValueError, KeyError) as exc:
        print(f"promote-collection: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "collection_id": artifact["collection_id"],
                "collection_version": artifact["provenance"]["collection_version"],
                "records": len(artifact["records"]),
                "bridge_players": len(artifact["bridge_players"]),
                "journey_hops": len(artifact.get("journey", [])),
                "playable_pairs": len(artifact.get("playable_cohort", {}).get("pairs", [])),
                "written": [str(p) for p in written],
                "published": args.publish_to is not None,
            },
            indent=2,
        )
    )
    return 0
