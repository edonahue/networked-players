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
import re
from collections import deque
from pathlib import Path
from typing import Any

from networked_players_contracts.collection import (
    MAX_BRIDGE_PLAYERS,
    MAX_VIA,
    MIN_BRIDGE_ARTISTS,
    MIN_BRIDGE_RECORDS,
    PLAYABLE_COHORT_V2_SCHEMA_VERSION,
    ROUTE_POLICY,
    GraphIndex,
    artist_key,
    collection_artifact_path,
    collection_failures,
    collection_version,
    collections_failures,
    dumps_stable,
    is_iso_timestamp,
    load_collections_directory,
    private_field_failures,
    string_values,
)

from .review_packet import build_collection_data, input_hash

SELECTION_KIND = "collection-selection"
APPROVAL_KIND = "collection-approval"
DEFAULT_STAGING_DIR = Path("local/collections-staging")
#: A private note or working title is matched against the public artifact only
#: when it is at least this many characters (after whitespace/case folding), as
#: a WHOLE phrase. Shorter private text ("jazz") is common vocabulary and would
#: refuse legitimate copy; the key denylist and field-by-field construction are
#: the primary guards, this is the backstop for pasted prose.
MIN_PRIVATE_TEXT_CHARS = 12
_APPROVAL_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "private",
        "collection_id",
        "input_hash",
        "cluster",
        "records",
        "journey",
        "playable",
    }
)


class CollectionPromotionError(ValueError):
    """The selection or inputs cannot become a public Collection. The message
    names every failure."""


# ---------------------------------------------------------------- selection


def validate_approval(approval: Any, *, collection_id: str) -> dict[str, Any]:
    """The owner's private approval file (ADR 0074): the cluster, the exact
    ordered records, the public journey order and whether to publish playable
    pairs. These are decisions that must not live in CLI flags (ADR 0031)."""
    if not isinstance(approval, dict) or set(approval) != _APPROVAL_KEYS:
        raise CollectionPromotionError(
            f"approval must be a JSON object with exactly keys {sorted(_APPROVAL_KEYS)}"
        )
    if approval["kind"] != APPROVAL_KIND or approval["private"] is not True:
        raise CollectionPromotionError(f"approval must have kind {APPROVAL_KIND!r}, private true")
    if approval["schema_version"] != 1:
        raise CollectionPromotionError("approval schema_version must be 1")
    if approval["collection_id"] != collection_id:
        raise CollectionPromotionError(
            f"approval is for collection {approval['collection_id']!r}, not {collection_id!r}"
        )
    cluster = approval["cluster"]
    if not isinstance(cluster, int) or isinstance(cluster, bool):
        raise CollectionPromotionError("approval cluster must be an integer")
    records = approval["records"]
    if not isinstance(records, list) or not all(isinstance(r, str) for r in records):
        raise CollectionPromotionError("approval records must be an array of record ids")
    journey = approval["journey"]
    if journey is not None and (
        not isinstance(journey, list) or not all(isinstance(r, str) for r in journey)
    ):
        raise CollectionPromotionError("approval journey must be null or an array of record ids")
    if not isinstance(approval["playable"], bool):
        raise CollectionPromotionError("approval playable must be true or false")
    return approval


def select_cluster(selection: Any, study: Any, approval: dict[str, Any]) -> dict[str, Any]:
    """Validate the private selection against its study and the owner's
    approval, and return `{"records", "journey", "playable", "working_title",
    "note"}`. The approval's records must be exactly the selection's kept
    records (the owner fixes the order); the private text is returned only so
    the caller can guard against leaking it."""
    if not isinstance(selection, dict) or selection.get("kind") != SELECTION_KIND:
        raise CollectionPromotionError(f"selection must be a {SELECTION_KIND!r} export")
    if selection.get("private") is not True:
        raise CollectionPromotionError("selection is not marked private; refusing to use it")
    try:
        data = build_collection_data(study)
        study_hash = input_hash(data)
    except Exception as exc:  # study shape errors surface as one clear message
        raise CollectionPromotionError(f"study JSON is not usable: {exc}") from exc
    if selection.get("input_hash") != study_hash:
        raise CollectionPromotionError(
            "selection was not exported from this study (input_hash differs)"
        )
    if approval["input_hash"] != study_hash:
        raise CollectionPromotionError("approval was not written for this selection (input_hash)")
    entries = selection.get("clusters")
    if not isinstance(entries, list):
        raise CollectionPromotionError("selection has no 'clusters' list")
    cluster = approval["cluster"]
    chosen = next((e for e in entries if isinstance(e, dict) and e.get("cluster") == cluster), None)
    if chosen is None:
        raise CollectionPromotionError(f"selection has no cluster {cluster}")
    if chosen.get("status") != "keep":
        raise CollectionPromotionError(
            f"cluster {cluster} has status {chosen.get('status')!r}; only 'keep' can be promoted"
        )
    study_albums = {a["id"] for c in data["clusters"] if c["index"] == cluster for a in c["albums"]}
    kept: list[str] = []
    for record in chosen.get("kept_records") or []:
        record_id = record.get("id") if isinstance(record, dict) else None
        if not isinstance(record_id, str) or record_id not in study_albums:
            raise CollectionPromotionError(
                f"kept record {record_id!r} is not in the study's cluster {cluster}"
            )
        if record_id in kept:
            raise CollectionPromotionError(f"kept record {record_id!r} is listed twice")
        kept.append(record_id)
    approved = approval["records"]
    if len(set(approved)) != len(approved) or set(approved) != set(kept):
        raise CollectionPromotionError(
            "approval records must be exactly the selection's kept records "
            f"(approved {sorted(set(approved))}, kept {sorted(kept)})"
        )
    return {
        "records": list(approved),
        "journey": approval["journey"],
        "playable": approval["playable"],
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


def bridge_players(
    gi: GraphIndex, records: list[str], artist_of: dict[str, Any]
) -> list[dict[str, Any]]:
    """Performers adjacent to the anchors of at least MIN_BRIDGE_RECORDS of the
    records whose records span at least MIN_BRIDGE_ARTISTS distinct primary
    artists (a primary artist is adjacent to every one of their own albums, so
    one artist's discography alone is not a bridge), most-connected first (ties
    by artist id), at most MAX_BRIDGE_PLAYERS."""
    on: dict[int, list[str]] = {}
    for record in records:
        for n in gi.performer_indices(record):
            on.setdefault(gi.node_ids[n], []).append(record)
    ranked = sorted(
        (
            item
            for item in on.items()
            if len(item[1]) >= MIN_BRIDGE_RECORDS
            and len({artist_of.get(r) for r in item[1]} - {None}) >= MIN_BRIDGE_ARTISTS
        ),
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
    album_by_id = {a["id"]: a for a in catalog.get("albums", []) if isinstance(a, dict)}
    artist_of = {r: artist_key(album_by_id.get(r)) for r in records}
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "collection_id": collection_id,
        "title": title,
        "intro": intro,
        "generated_at": generated_at,
        "records": list(records),
        "bridge_players": bridge_players(gi, records, artist_of),
    }
    if attribution is not None:
        artifact["attribution"] = {
            "label": attribution.get("label", ""),
            "source_url": attribution.get("source_url", ""),
        }
    if journey:
        artifact["journey"] = _journey(gi, records, journey, artist_of)
    if playable:
        artifact["playable_cohort"] = _playable(gi, records, artist_of)
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


def _journey(
    gi: GraphIndex, records: list[str], order: list[str], artist_of: dict[str, Any]
) -> list[dict[str, Any]]:
    if len(order) < 2:
        raise CollectionPromotionError("--journey needs at least two record ids")
    unknown = [r for r in order if r not in records]
    if unknown:
        raise CollectionPromotionError(f"journey records not in the collection: {unknown}")
    if len(set(order)) != len(order):
        raise CollectionPromotionError("journey must not revisit a record")
    hops: list[dict[str, Any]] = []
    for a, b in itertools.pairwise(order):
        if artist_of.get(a) is not None and artist_of.get(a) == artist_of.get(b):
            raise CollectionPromotionError(
                f"journey hop {a} -> {b}: both records have the same primary artist"
            )
        via = _route_tree(gi, a, [b]).get(b)
        if via is None:
            raise CollectionPromotionError(
                f"journey hop {a} -> {b}: no route of at most {MAX_VIA} performers in the graph"
            )
        hops.append({"from_record": a, "to_record": b, **_route_fields(gi, via)})
    return hops


def _playable(gi: GraphIndex, records: list[str], artist_of: dict[str, Any]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(records):
        # Same-primary-artist pairs bridge nothing and are never published.
        targets = [
            b
            for b in records[i + 1 :]
            if artist_of.get(a) is None or artist_of.get(a) != artist_of.get(b)
        ]
        routes = _route_tree(gi, a, targets)
        for b in targets:
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


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _private_fragments(text: str) -> list[str]:
    """Whole private text plus each sentence/line of it, normalised, keeping
    only fragments long enough to be meaningful (MIN_PRIVATE_TEXT_CHARS)."""
    pieces = [text, *re.split(r"[.!?;\n]+", text)]
    return sorted({n for p in pieces if len(n := _norm(p)) >= MIN_PRIVATE_TEXT_CHARS})


def _assert_no_private_text(
    artifact: dict[str, Any], *, working_title: str, note: str, title: str
) -> None:
    """Belt and braces on top of the explicit field-by-field construction: the
    selection's note and working title must not surface in the output. Compared
    against the DECODED string values (so quotes and backslashes in a note do
    not hide it), as whole phrases of at least MIN_PRIVATE_TEXT_CHARS. A working
    title becomes public only by being passed as `--title`: a working title equal
    to the title is exempt in the `title` field."""
    problems = private_field_failures(artifact)
    values = [(path, _norm(text)) for path, text in string_values(artifact)]
    checks = [("note", frag, False) for frag in _private_fragments(note)]
    exempt_title = _norm(working_title) == _norm(title)
    checks += [("working title", frag, exempt_title) for frag in _private_fragments(working_title)]
    for label, fragment, title_exempt in checks:
        pattern = re.compile(r"(?<!\w)" + re.escape(fragment) + r"(?!\w)")
        for path, value in values:
            if title_exempt and path == "$.title":
                continue
            if pattern.search(value):
                problems.append(
                    f"the selection's {label} text appears in the public artifact ({path})"
                )
                break
    if problems:
        raise CollectionPromotionError("; ".join(problems))


# ---------------------------------------------------------------------- IO


def _refuse_public_path(path: Path) -> None:
    """Staging never lands under `apps/web/public/`. The path is resolved first,
    so `..` and symlinks cannot walk around the check."""
    parts = path.resolve().parts
    if any(parts[i : i + 3] == ("apps", "web", "public") for i in range(len(parts) - 2)):
        raise CollectionPromotionError(
            f"refusing to stage under apps/web/public/: {path} (use --publish-to, explicitly)"
        )


def _require_public_data_root(path: Path) -> Path:
    """`--publish-to` must be the public data root itself (`.../apps/web/public/
    data`, containing `catalog/albums.v1.json`), so a typo cannot create a served
    but never-validated directory elsewhere under `public/`."""
    resolved = path.resolve()
    if (
        resolved.parts[-4:] != ("apps", "web", "public", "data")
        or not (resolved / "catalog" / "albums.v1.json").is_file()
    ):
        raise CollectionPromotionError(
            f"--publish-to must be the public data root (apps/web/public/data, containing "
            f"catalog/albums.v1.json), got {path}"
        )
    return resolved


def write_collection(
    directory: Path,
    artifact: dict[str, Any],
    *,
    catalog: dict[str, Any],
    graph: dict[str, Any],
) -> list[Path]:
    """Write `<id>.v1.json` and merge the entry into `index.v1.json` in
    `directory`, then validate the resulting directory as a whole (every entry
    in it is accounted for, as `validate-public-artifacts` will)."""
    cid = artifact["collection_id"]
    loaded = load_collections_directory(directory) or {"index": None, "files": {}, "problems": []}
    index = loaded["index"]
    if not isinstance(index, dict) or not isinstance(index.get("collections"), list):
        index = {"schema_version": 1, "collections": []}
    entries = [
        e for e in index["collections"] if isinstance(e, dict) and e.get("collection_id") != cid
    ]
    entries.append(
        {
            "collection_id": cid,
            "title": artifact["title"],
            "artifact_path": collection_artifact_path(cid),
            "record_count": len(artifact["records"]),
            "collection_version": artifact["provenance"]["collection_version"],
        }
    )
    index = {**index, "collections": sorted(entries, key=lambda e: str(e["collection_id"]))}
    files = {**loaded["files"], cid: artifact}
    failures = collections_failures(
        {"index": index, "files": files, "problems": loaded["problems"]}, catalog, graph
    )
    if failures:
        raise CollectionPromotionError(
            "the resulting collections directory fails validation:\n- " + "\n- ".join(failures)
        )
    directory.mkdir(parents=True, exist_ok=True)
    artifact_path = directory / f"{cid}.v1.json"
    index_path = directory / "index.v1.json"
    artifact_path.write_text(dumps_stable(artifact), encoding="utf-8")
    index_path.write_text(dumps_stable(index), encoding="utf-8")
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
        if not is_iso_timestamp(args.generated_at):
            raise CollectionPromotionError("--generated-at must be an ISO-8601 timestamp")
        text: dict[str, Any] = load_public_text(args.text_file) if args.text_file else {}
        title = args.title if args.title is not None else text.get("title", "")
        intro = args.intro if args.intro is not None else text.get("intro", "")
        selection = json.loads(args.selection.read_text())
        study = json.loads(args.study.read_text())
        catalog = json.loads(args.catalog.read_text())
        graph = json.loads(args.graph.read_text())
        approval = validate_approval(
            json.loads(args.approval.read_text()), collection_id=args.collection_id
        )
        chosen = select_cluster(selection, study, approval)
        if args.publish_to is not None:
            target = _require_public_data_root(args.publish_to) / "collections"
        else:
            _refuse_public_path(args.output_dir)
            target = args.output_dir
        artifact = build_collection(
            records=chosen["records"],
            catalog=catalog,
            graph=graph,
            collection_id=args.collection_id,
            title=title,
            intro=intro,
            generated_at=args.generated_at,
            attribution=text.get("attribution"),
            journey=chosen["journey"],
            playable=chosen["playable"],
        )
        _assert_no_private_text(
            artifact,
            working_title=chosen["working_title"],
            note=chosen["note"],
            title=title,
        )
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
