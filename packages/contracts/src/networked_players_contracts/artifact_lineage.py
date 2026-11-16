"""Declared lineage between public artifacts (ADR 0072 section 1).

A builder that reads upstream public artifacts stamps `provenance.inputs`: a
map `{artifact_name: content_version}` of the exact versions it consumed.
`artifact_lineage_report` is the one generic rule that checks them: for every
*live* artifact that declares inputs, each declared non-null version must
equal the upstream artifact's current version, and a declared name must be a
known artifact.

Why content versions and not file hashes: every artifact is re-formatted by
Prettier after its builder writes it (`docs/OPERATOR_SETUP.md`), so a hash of
file bytes is stale the moment it is committed. The per-artifact `*_version`
fields hash semantic content through `canonical.content_hash` and survive
reformatting.

Stated limit: artifacts committed before this module declare no inputs and
cannot be given lineage retroactively (their parameters and non-committed
inputs were never recorded). An artifact that declares no inputs PASSES; the
report lists it under `undeclared` so the gap is visible as data until the
next rebuild closes it.

Artifact classes:

- `live`: rebuilt with the catalog and checked by the generic rule.
- `frozen`: `game/generations/*` -- deliberately bound to old catalog and pool
  versions (ADR 0041, ADR 0066). Not loaded by `public_artifacts_failures`, so
  never visited; named here so the class is explicit.
- `appended`: the daily manifest, extended outside any rebuild. Skipped.
- `source`: the approved pool, a hand-curated record rather than a built
  artifact. Skipped.

Pure Python and dependency-free (runs on 1 GB Raspberry Pi workers).
"""

from __future__ import annotations

from typing import Any

LIVE = "live"
FROZEN = "frozen"
APPENDED = "appended"
SOURCE = "source"

# Keyed by `PUBLIC_ARTIFACT_GROUPS` names (a test pins the two in sync).
ARTIFACT_CLASSES: dict[str, str] = {
    "catalog": LIVE,
    "album_art_registry": LIVE,
    "connection_guesser": LIVE,
    "connection_daily_manifest": APPENDED,
    "record_routes": LIVE,
    "challenge": LIVE,
    "contributor_index": LIVE,
    "album_hop_distances": LIVE,
    "pathfinding_graph": LIVE,
    "prominence": LIVE,
    "album_credit_membership": LIVE,
    "evidence_release_registry": LIVE,
    "search_index": LIVE,
    "approved_pool": SOURCE,
}

# Published paths (relative to apps/web/public/data/) of the frozen class.
FROZEN_PATH_PATTERNS: tuple[str, ...] = ("game/generations/*",)

# Where each artifact's own content version lives. For the two-file artifacts
# (Connection Guesser, Record Routes) the universe file is the carrier; its
# provenance equals the rounds file's by contract.
VERSION_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "catalog": ("catalog_version",),
    "album_art_registry": ("art_version",),
    "connection_guesser": ("provenance", "artifact_version"),
    "record_routes": ("provenance", "artifact_version"),
    "challenge": ("provenance", "challenge_version"),
    "contributor_index": ("contributor_index_version",),
    "album_hop_distances": ("album_hop_distances_version",),
    "pathfinding_graph": ("pathfinding_graph_version",),
    "prominence": ("prominence_version",),
    "album_credit_membership": ("album_credit_membership_version",),
    "evidence_release_registry": ("evidence_release_registry_version",),
    "search_index": ("search_index_version",),
}

# The real dependency edges: which upstream public artifacts each builder
# reads. Corpus roots and policy files are not public artifacts and are not
# listed. See `data/contracts/artifact-lineage-v1.md`.
EXPECTED_INPUTS: dict[str, tuple[str, ...]] = {
    "album_art_registry": ("catalog",),
    "connection_guesser": ("catalog",),
    "record_routes": ("catalog",),
    "challenge": ("catalog",),
    "album_credit_membership": ("catalog",),
    "pathfinding_graph": ("catalog", "album_credit_membership"),
    "evidence_release_registry": (
        "catalog",
        "challenge",
        "record_routes",
        "pathfinding_graph",
        "album_art_registry",
    ),
    "prominence": ("pathfinding_graph", "evidence_release_registry"),
    "contributor_index": ("catalog", "challenge", "record_routes", "evidence_release_registry"),
    "album_hop_distances": ("catalog", "challenge", "record_routes", "contributor_index"),
    "search_index": ("catalog", "contributor_index"),
}


# Artifacts whose top-level `provenance` object exists only to carry
# `inputs` (they had no provenance before lineage). Anything else inside it is
# a malformed artifact, not something to ignore.
INPUTS_ONLY_PROVENANCE: frozenset[str] = frozenset(
    name
    for name, path in VERSION_FIELD_PATHS.items()
    if name != "catalog" and path[0] != "provenance"
)


def provenance_shape_failures(name: str, payload: Any) -> list[str]:
    """A present `provenance` must be an object; for the inputs-only artifacts
    it may hold nothing but `inputs`. Absent is fine."""
    if not isinstance(payload, dict) or "provenance" not in payload:
        return []
    provenance = payload["provenance"]
    if not isinstance(provenance, dict):
        return [f"{name} provenance must be an object"]
    if name in INPUTS_ONLY_PROVENANCE:
        extra = sorted(set(provenance) - {"inputs"})
        if extra:
            return [f"{name} provenance may only contain 'inputs'; unexpected keys: {extra}"]
    return []


def artifact_content_version(name: str, payload: Any) -> str | None:
    """The artifact's own content version, or `None` when it carries none
    (e.g. a challenge built before `challenge_version` existed)."""
    path = VERSION_FIELD_PATHS.get(name)
    if path is None:
        return None
    node: Any = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, str) and node else None


def declared_inputs(payload: Any) -> Any:
    """`provenance.inputs` exactly as written, or `None` when absent."""
    if not isinstance(payload, dict):
        return None
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return None
    return provenance.get("inputs")


def inputs_shape_failures(label: str, inputs: Any) -> list[str]:
    if not isinstance(inputs, dict):
        return [f"{label} provenance.inputs must be an object"]
    return [
        f"{label} provenance.inputs[{name!r}] must be a version string or null"
        for name, version in inputs.items()
        if version is not None and not (isinstance(version, str) and version)
    ]


def artifact_lineage_report(artifacts: dict[str, Any]) -> dict[str, Any]:
    """Apply the generic lineage rule.

    `artifacts` maps artifact name -> loaded payload (absent names are simply
    not checked). Returns `{"failures": {name: [...]}, "undeclared": [...],
    "partially_declared": {name: [missing upstream names]}}`;
    `failures` is attributed to the DOWNSTREAM artifact and names both ends.
    `undeclared` lists live artifacts that have upstream edges but declare no
    `provenance.inputs` -- data, not a failure."""
    failures: dict[str, list[str]] = {}
    undeclared: list[str] = []
    partial: dict[str, list[str]] = {}
    for name, payload in artifacts.items():
        if ARTIFACT_CLASSES.get(name) != LIVE or payload is None:
            continue
        malformed = provenance_shape_failures(name, payload)
        if malformed:
            failures.setdefault(name, []).extend(malformed)
            continue
        inputs = declared_inputs(payload)
        if inputs is None:
            if name in EXPECTED_INPUTS:
                undeclared.append(name)
            continue
        shape = inputs_shape_failures(name, inputs)
        if shape:
            failures.setdefault(name, []).extend(shape)
            continue
        # Declaring some inputs but not every expected edge is allowed (a
        # caller may legitimately omit an optional input) but it is a gap in
        # what is being checked, so it is reported as data like `undeclared`.
        missing = [u for u in EXPECTED_INPUTS.get(name, ()) if u not in inputs]
        if missing:
            partial[name] = missing
        for upstream, declared in inputs.items():
            if upstream not in VERSION_FIELD_PATHS:
                failures.setdefault(name, []).append(
                    f"{name} declares input {upstream!r}, which is not a known artifact"
                )
                continue
            if declared is None or upstream not in artifacts:
                continue
            current = artifact_content_version(upstream, artifacts[upstream])
            if current != declared:
                failures.setdefault(name, []).append(
                    f"{name} was built from {upstream} version {declared!r} but the current "
                    f"{upstream} is {current!r} -- rebuild {name} (and everything downstream "
                    "of it)"
                )
    return {
        "failures": failures,
        "undeclared": sorted(undeclared),
        "partially_declared": {name: partial[name] for name in sorted(partial)},
    }
