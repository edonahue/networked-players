"""Canonical, dependency-free Connection Guesser rounds-artifact validation.

Validates the flagship Connection Guesser's real `GameUniverse`/`GameRounds`
pair (`apps/web/public/data/game/universe.v1.json` /
`apps/web/public/data/game/rounds.v1.json`, `apps/web/src/game/types.ts`): a
one-hop round's answer is a performer explicitly credited on BOTH displayed
albums directly (`endpoints`/`answer_set`), a two-hop round hides a middle
album bridged by two independently-guessed performer sets
(`middle`/`bridge_answer_sets`). This is a genuinely different contract from
`networked_players_contracts.rounds`'s Record Routes **path** semantic
(`from_album_id`/`to_album_id`/`hops`) -- see that module's docstring. Both
pairs have historically been published at the same file names in different
directories; do not assume "rounds.v1" alone identifies which contract
applies (see ADR 0043).

Mirrors `cohort.py`'s/`rounds.py`'s structure: pure-Python, no
lxml/pyarrow/duckdb, safe to run on the Pi fleet and in the web build for
independent verification of an already-generated pair.

## Validator hierarchy (corrective slice 4.6, ADR 0043) -- read before adding
## a check or describing what this module proves

There are two validators for this contract. Neither should be described as
stronger than its actual inputs allow:

- **This module** and **generation-time**
  (`packages/graph-core/.../connection_rounds.py
  ::validate_connection_rounds_artifact`) both operate on the SAME inputs:
  the already-built `universe`/`rounds` dicts, no live database connection.
  Both can (and do) recompute exact one-hop/two-hop performer intersections,
  "no direct eligible performer between two-hop endpoints", evidence
  coverage, distractor invalidity, round-id and `artifact_version`
  recomputation, and metadata/privacy checks -- all from the UNIVERSE's own
  published `credits[]` (a complete per-album index, not an evidence-only
  subset -- see ADR 0043's Finding 7). A passing run of EITHER proves
  "internally consistent, and consistent with its own published universe" --
  never describe it as "independently verified against the live Discogs
  graph," because neither validator queries it.
- The one thing generation-time validation does NOT independently re-verify
  either: **two-hop middle-album uniqueness across the entire eligible
  catalog**. That guarantee is enforced by construction inside
  `generate_connection_round_pool`'s discovery loop (which searches every
  album in the input catalog, not just the smaller set later referenced by a
  round) -- a property of how the pool was built, not something either
  validator re-derives post-hoc from the published pair. If that guarantee
  is ever in doubt, the fix is re-running discovery, not strengthening
  either validator.
- The practical difference between the two is dependency footprint, not
  proof strength: this module is pure Python (no lxml/pyarrow/duckdb), safe
  for the Pi fleet and the web build; the graph-core copy runs inside the
  same process as generation and could, in principle, be extended to
  re-query the live graph for a check like middle-uniqueness -- as of this
  writing it does not.

If the two validators disagree, treat it as a bug in whichever is stricter by
mistake.
"""

from __future__ import annotations

import re
from typing import Any, cast

from .canonical import content_hash, stable_id_digest

CONNECTION_ROUNDS_SCHEMA_VERSION = 1

_ROUND_ID_PATTERN = re.compile(r"^conn-[0-9a-f]{10}$")
_KINDS = frozenset({"one_hop", "two_hop"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
_FORBIDDEN_SUBSTRINGS = (
    "/" + "home/",
    "data/" + "private",
    "local" + "/",
    "DISCOGS" + "_TOKEN",
    "." + "ssh",
)
_FORBIDDEN_PHRASES = ("worked with", "collaborated with", "influenced")
_PROVENANCE_REQUIRED_FIELDS = (
    "source",
    "license",
    "snapshot_date",
    "generated_by",
    "note",
    "catalog_version",
    "pool_version",
    "artifact_version",
)


def round_content_fingerprint(round_json: dict[str, Any]) -> str:
    """Recompute a round's content fingerprint from its own published data --
    must agree with `networked_players_graph_core.connection_rounds
    ::round_content_fingerprint` (shares the same `content_hash` primitive,
    not merely a structural mirror)."""
    return f"rfp-{content_hash(round_json, length=16)}"


def _artifact_version(rounds_json: list[Any], snapshot_date: str) -> str:
    """Must agree byte-for-byte with the generation-time mirror
    (`networked_players_graph_core.connection_rounds::artifact_version`):
    hashes the rounds array in its PUBLISHED ORDER, not sorted -- order is
    part of the artifact (corrective slice 5.1)."""
    fingerprints = [round_content_fingerprint(r) for r in rounds_json if isinstance(r, dict)]
    return f"connection-artifact-v1-{snapshot_date}-{content_hash(fingerprints, length=12)}"


def _str_ids(items: Any) -> list[str] | None:
    if not isinstance(items, list):
        return None
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return None
        out.append(cast(str, item["id"]))
    return out


def _int_ids(items: Any) -> list[int] | None:
    if not isinstance(items, list):
        return None
    out: list[int] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            return None
        out.append(cast(int, item["id"]))
    return out


def _recomputed_one_hop_id(round_json: dict[str, Any]) -> str | None:
    ids = _str_ids(round_json.get("endpoints"))
    answer_ids = _int_ids(round_json.get("answer_set"))
    if ids is None or len(ids) != 2 or answer_ids is None:
        return None
    answer_part = ",".join(str(a) for a in sorted(answer_ids))
    return f"conn-{stable_id_digest('1h', *sorted(ids), answer_part)}"


def _recomputed_two_hop_id(round_json: dict[str, Any]) -> str | None:
    endpoint_ids = _str_ids(round_json.get("endpoints"))
    middle = round_json.get("middle")
    bridges = round_json.get("bridge_answer_sets")
    if (
        endpoint_ids is None
        or len(endpoint_ids) != 2
        or not isinstance(middle, dict)
        or not isinstance(bridges, list)
        or len(bridges) != 2
    ):
        return None
    middle_album = middle.get("album")
    middle_id = middle_album.get("id") if isinstance(middle_album, dict) else None
    if not isinstance(middle_id, str):
        return None
    bridge_a_ids = _int_ids(bridges[0])
    bridge_c_ids = _int_ids(bridges[1])
    if bridge_a_ids is None or bridge_c_ids is None:
        return None
    bridge_a_part = ",".join(str(i) for i in sorted(bridge_a_ids))
    bridge_c_part = ",".join(str(i) for i in sorted(bridge_c_ids))
    digest = stable_id_digest(
        "2h", endpoint_ids[0], endpoint_ids[1], middle_id, bridge_a_part, bridge_c_part
    )
    return f"conn-{digest}"


def _seed_key_paths(obj: Any, path: str = "") -> list[str]:
    """Recursively collect dotted paths to any dict key literally named
    ``seed`` -- must agree with graph-core's generation-time mirror
    (`connection_rounds.py::_find_seed_keys`)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else str(key)
            if key == "seed":
                found.append(child)
            found.extend(_seed_key_paths(value, child))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            found.extend(_seed_key_paths(item, f"{path}[{index}]"))
    return found


def _privacy_failures(artifact: dict[str, Any], *, name: str) -> list[str]:
    serialized = str(artifact)
    failures = [
        f"{name} contains forbidden substring: {forbidden!r}"
        for forbidden in _FORBIDDEN_SUBSTRINGS
        if forbidden in serialized
    ]
    lowered = serialized.lower()
    failures.extend(
        f"{name} contains forbidden phrase: {phrase!r}"
        for phrase in _FORBIDDEN_PHRASES
        if phrase in lowered
    )
    return failures


def connection_rounds_failures(universe: Any, rounds: Any) -> list[str]:
    """Return every contract failure in a Connection Guesser universe.v1/
    rounds.v1 pair."""
    failures: list[str] = []
    if not isinstance(universe, dict):
        return ["universe artifact must be an object"]
    if not isinstance(rounds, dict):
        return ["rounds artifact must be an object"]

    if universe.get("schema_version") != CONNECTION_ROUNDS_SCHEMA_VERSION:
        failures.append(f"universe schema_version must be {CONNECTION_ROUNDS_SCHEMA_VERSION}")
    if rounds.get("schema_version") != CONNECTION_ROUNDS_SCHEMA_VERSION:
        failures.append(f"rounds schema_version must be {CONNECTION_ROUNDS_SCHEMA_VERSION}")
    if universe.get("provenance") != rounds.get("provenance"):
        failures.append("universe and rounds provenance must match exactly")

    album_ids: set[Any] = {a.get("id") for a in universe.get("albums", []) if isinstance(a, dict)}
    contributor_ids: set[Any] = {
        c.get("id") for c in universe.get("contributors", []) if isinstance(c, dict)
    }
    release_ids: set[Any] = {
        r.get("id") for r in universe.get("releases", []) if isinstance(r, dict)
    }

    round_entries = rounds.get("rounds", [])
    if not isinstance(round_entries, list):
        return ["rounds.rounds must be an array"]

    seen_round_ids: set[Any] = set()
    for round_json in round_entries:
        if not isinstance(round_json, dict):
            failures.append("round must be an object")
            continue
        round_id = round_json.get("id")
        if round_id in seen_round_ids:
            failures.append(f"duplicate round id: {round_id}")
        seen_round_ids.add(round_id)
        if not isinstance(round_id, str) or not _ROUND_ID_PATTERN.match(round_id):
            failures.append(f"round id {round_id!r} is not a stable content-derived id")
        else:
            recomputed = (
                _recomputed_two_hop_id(round_json)
                if round_json.get("kind") == "two_hop"
                else _recomputed_one_hop_id(round_json)
            )
            if recomputed is not None and recomputed != round_id:
                failures.append(
                    f"round id {round_id} does not match its own recomputed content "
                    f"(expected {recomputed}) -- id or semantic fields were edited "
                    f"inconsistently"
                )
        if round_json.get("pool") != "real-records":
            failures.append(f"round {round_id} pool must be 'real-records'")
        kind = round_json.get("kind")
        if kind not in _KINDS:
            failures.append(f"round {round_id} has invalid kind: {kind!r}")
        if round_json.get("difficulty") not in _DIFFICULTIES:
            failures.append(f"round {round_id} has invalid difficulty")

        answer_set = round_json.get("answer_set", [])
        if kind == "one_hop" and not answer_set:
            failures.append(f"round {round_id} has an empty answer set")
        answer_ids = {a.get("id") for a in answer_set if isinstance(a, dict)}
        bridges = round_json.get("bridge_answer_sets") or []
        bridge_ids: set[Any] = {
            a.get("id") for group in bridges for a in group if isinstance(a, dict)
        }
        all_valid_ids = answer_ids | bridge_ids

        evidence = round_json.get("evidence", [])
        if not evidence:
            failures.append(f"round {round_id} has no evidence rows")
        evidence_ids = {row.get("contributor_id") for row in evidence if isinstance(row, dict)}
        for aid in all_valid_ids:
            if aid not in evidence_ids:
                failures.append(f"round {round_id} answer {aid} lacks evidence")

        for distractor in round_json.get("distractors", []):
            if not isinstance(distractor, dict):
                continue
            if distractor.get("id") in all_valid_ids:
                failures.append(f"round {round_id} distractor {distractor.get('id')} is an answer")
            if distractor.get("id") not in contributor_ids:
                failures.append(
                    f"round {round_id} distractor {distractor.get('id')} not in universe"
                )

        for clue in round_json.get("clues", []):
            if isinstance(clue, dict) and clue.get("kind") == "eliminate":
                for eliminated_id in clue.get("eliminate_ids") or []:
                    if eliminated_id in all_valid_ids:
                        failures.append(
                            f"round {round_id} eliminate clue targets valid answer {eliminated_id}"
                        )

        for endpoint in round_json.get("endpoints", []):
            if not isinstance(endpoint, dict) or endpoint.get("id") not in album_ids:
                failures.append(f"round {round_id} endpoint not in universe")

        if kind == "two_hop":
            middle = round_json.get("middle")
            if not middle or not bridges or len(bridges) != 2:
                failures.append(f"two-hop round {round_id} missing middle/bridge_answer_sets")
            else:
                choices = middle.get("choices", [])
                middle_album_id = middle.get("album", {}).get("id")
                if not any(c.get("id") == middle_album_id for c in choices):
                    failures.append(f"round {round_id} middle answer missing from its own choices")
                if not bridges[0] or not bridges[1]:
                    failures.append(f"round {round_id} needs at least one bridge answer per side")

    for artifact, name in ((universe, "universe"), (rounds, "rounds")):
        failures.extend(
            f"{name} must not have a 'seed' key ({seed_path})"
            for seed_path in _seed_key_paths(artifact)
        )
        failures.extend(_privacy_failures(artifact, name=name))

    for field_name in _PROVENANCE_REQUIRED_FIELDS:
        if not universe.get("provenance", {}).get(field_name):
            failures.append(f"universe.provenance.{field_name} is required")

    # Recomputable from the published pair alone -- no source-graph
    # dependency, so this validator can (and must) prove it, unlike a check
    # that would require rediscovering ground truth (see the module
    # docstring's validator-hierarchy note).
    snapshot_date = universe.get("provenance", {}).get("snapshot_date")
    if isinstance(snapshot_date, str) and isinstance(round_entries, list):
        expected_artifact_version = _artifact_version(round_entries, snapshot_date)
        actual_artifact_version = universe.get("provenance", {}).get("artifact_version")
        if actual_artifact_version != expected_artifact_version:
            failures.append(
                f"provenance.artifact_version {actual_artifact_version!r} does not match "
                f"the rounds array's own recomputed content (expected "
                f"{expected_artifact_version!r})"
            )

    # Universe-derived exact intersection check: recomputed from the
    # UNIVERSE's own published credits[] (a complete per-album index, see
    # ADR 0043 Finding 7) -- this proves internal consistency between the
    # round and the universe it ships next to, not correctness against the
    # original Discogs graph (see the module docstring).
    performers_by_album: dict[Any, set[Any]] = {a: set() for a in album_ids}
    for credit in universe.get("credits", []):
        if isinstance(credit, dict) and credit.get("release_id") in performers_by_album:
            performers_by_album[credit["release_id"]].add(credit.get("contributor_id"))
    for round_json in round_entries:
        if not isinstance(round_json, dict):
            continue
        round_id = round_json.get("id")
        endpoints = round_json.get("endpoints", [])
        if len(endpoints) != 2:
            continue
        a_id, c_id = endpoints[0].get("id"), endpoints[1].get("id")
        if round_json.get("kind") == "one_hop":
            derived = performers_by_album.get(a_id, set()) & performers_by_album.get(c_id, set())
            published = {a.get("id") for a in round_json.get("answer_set", [])}
            if derived != published:
                failures.append(
                    f"round {round_id}: answer_set {sorted(published, key=str)} does not "
                    f"exactly match the universe-derived intersection "
                    f"{sorted(derived, key=str)}"
                )
        elif round_json.get("kind") == "two_hop":
            middle = round_json.get("middle") or {}
            middle_id = (middle.get("album") or {}).get("id")
            bridges = round_json.get("bridge_answer_sets") or [[], []]
            derived_a = performers_by_album.get(a_id, set()) & performers_by_album.get(
                middle_id, set()
            )
            derived_c = performers_by_album.get(middle_id, set()) & performers_by_album.get(
                c_id, set()
            )
            published_a = {a.get("id") for a in bridges[0]}
            published_c = {a.get("id") for a in bridges[1]}
            if derived_a != published_a:
                failures.append(f"round {round_id}: bridge_answer_sets[0] does not exactly match")
            if derived_c != published_c:
                failures.append(f"round {round_id}: bridge_answer_sets[1] does not exactly match")
            direct_shared = performers_by_album.get(a_id, set()) & performers_by_album.get(
                c_id, set()
            )
            if direct_shared:
                failures.append(
                    f"round {round_id} is two-hop but its own endpoints share a direct "
                    f"eligible performer {sorted(direct_shared, key=str)} -- premise violated"
                )

    source = str(universe.get("provenance", {}).get("source", "")).lower()
    generated_by = str(universe.get("provenance", {}).get("generated_by", "")).lower()
    if "discogs" not in source:
        failures.append("universe provenance.source does not identify a real Discogs source")
    if "synthetic" in generated_by or "ci placeholder" in generated_by:
        failures.append("universe provenance.generated_by marks this as a synthetic fixture")

    for credit in universe.get("credits", []):
        if not isinstance(credit, dict):
            continue
        if credit.get("contributor_id") not in contributor_ids:
            failures.append(f"credit references unknown contributor {credit.get('contributor_id')}")
        if credit.get("release_id") not in release_ids:
            failures.append(f"credit references unknown release {credit.get('release_id')}")

    return failures
