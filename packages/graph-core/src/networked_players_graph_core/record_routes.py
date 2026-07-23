"""Record Routes: the path-guessing mode's real artifact pair.

Record Routes is a **distinct** game from the flagship Connection Guesser
(ADR 0046). A round shows two real albums and asks the player to guess the
**length of the documented credit path** between them (one hop or two), then
optionally name a connecting artist, then reveals the full path with evidence
at every hop. This is the album->artist->album **path** semantic
(`from_album_id`/`to_album_id`/`hops[]`), NOT the Connection Guesser's
"performer credited on both displayed albums" intersection semantic.

This module reuses the tested path *discovery* in `rounds_generator.py`
(`generate_round_pool`) and the universe assembly in `rounds.py`
(`build_rounds_v1`), then emits a proper Record Routes contract:

- its own artifact namespace (`apps/web/public/data/routes/{universe,rounds}.v1.json`),
  never the Connection Guesser's `game/rounds.v1.json` or its daily manifest;
- an explicit `mode: "record_routes"` on both artifacts;
- **content-derived stable route ids** (`route-<hash>`), never the ordinal
  `round-000001` ids `generate_round_pool` assigns internally -- so the pool can
  be regenerated/reordered without an unchanged route's id moving;
- deterministic `pool_version` (membership) and `artifact_version` (complete
  ordered content), like the Connection Guesser pool (ADR 0043/0045);
- **art-free** album refs: cover art is resolved by canonical album id from the
  shared album-art registry (ADR 0045), never embedded here.
"""

from __future__ import annotations

from typing import Any

from networked_players_contracts.canonical import content_hash, stable_id_digest
from networked_players_contracts.record_routes import record_routes_failures

from .challenge import MatchedAlbum
from .graph import CreditGraph
from .rounds import ROUNDS_SCHEMA_VERSION, build_rounds_v1
from .rounds_generator import generate_round_pool

RECORD_ROUTES_SCHEMA_VERSION = ROUNDS_SCHEMA_VERSION
RECORD_ROUTES_MODE = "record_routes"


class RecordRoutesValidationError(RuntimeError):
    """Raised when a Record Routes universe/rounds pair violates its contract."""


def _hop_signature(hop: dict[str, Any]) -> str:
    lo, hi = sorted((int(hop["artist_a_id"]), int(hop["artist_b_id"])))
    return f"{hop['release_id']}:{lo}:{hi}"


def stable_route_id(round_json: dict[str, Any]) -> str:
    """A deterministic, content-derived route id from the round's own semantic
    fields -- endpoints + the ordered hop signatures (release + the unordered
    artist pair per hop). Presentation-independent and stable across
    regeneration; two runs that discover the same documented path keep the
    same id.

    **Orientation-sensitive by design.** `endpoints` is sorted, so swapping
    which album is `from`/`to` alone never changes the id -- but the hop
    *sequence* is not canonicalized, so the same conceptual path traversed
    in the opposite direction (hops reversed) hashes to a DIFFERENT id. This
    is intentional, not an oversight: `from_artist_id`/`to_artist_id` are
    meaningfully tied to which album renders as sleeve A vs. sleeve B, which
    is itself a real, displayed distinction, not an arbitrary presentation
    choice to canonicalize away. In practice this never causes an id to
    drift across a real regeneration: `_two_hop_candidates`' `i < c`
    backbone-index iteration and artist-id-sorted `from`/`to` assignment
    mean this generator only ever discovers each unordered artist pair
    once, in one orientation, on every run (proven by
    `test_regeneration_is_byte_identical_except_nothing_random`, and by
    `test_reversed_orientation_is_a_different_id_by_design` pinning the
    reverse-hop-order case explicitly)."""
    endpoints = sorted((str(round_json["from_album_id"]), str(round_json["to_album_id"])))
    hop_part = ",".join(_hop_signature(h) for h in round_json.get("hops", []))
    return f"route-{stable_id_digest('rr', *endpoints, hop_part)}"


def record_routes_pool_version(round_ids: list[str], snapshot_date: str) -> str:
    """Membership hash: sorted route ids only. Unchanged by an edit to a
    single round's evidence/distractors when the set of routes is unchanged."""
    digest = content_hash(sorted(round_ids), length=12)
    return f"routes-v1-{snapshot_date}-{digest}"


def record_routes_artifact_version(
    *,
    albums: list[dict[str, Any]],
    rounds_json: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    artists: list[dict[str, Any]],
    snapshot_date: str,
) -> str:
    """Complete-content hash of everything actually published and
    player-visible -- the ordered rounds array, the universe's album refs,
    and the evidence releases/artists a route's hop/evidence lookups
    resolve against. Changes on ANY published field change (a route's own
    content, an album's title/year, a release's credit role text, an
    artist's display name) or a reordering of any of the four arrays, even
    with identical membership.

    Deliberately broader than hashing `rounds_json` alone (the original
    slice-6 definition, corrected here -- see ADR 0046's slice-9 addendum).
    The Connection Guesser's `artifact_version` (ADR 0043/0045) can safely
    hash only its `rounds[]` array because that contract embeds every
    player-visible/evidentiary field *inside* each round object. Record
    Routes normalizes evidence into separate `releases[]`/`artists[]`
    arrays and album refs into `universe.albums[]`, referenced by id --
    a route's own `rounds[]` entry only carries `hops[].role_a/role_b`
    inline, so hashing it alone would miss a silent edit to a displayed
    artist name or album title."""
    payload = {"albums": albums, "rounds": rounds_json, "releases": releases, "artists": artists}
    digest = content_hash(payload, length=12)
    return f"routes-artifact-v1-{snapshot_date}-{digest}"


def build_record_routes_pool(
    graph: CreditGraph,
    matched_albums: list[MatchedAlbum],
    *,
    one_hop_target: int,
    two_hop_target: int,
    snapshot_date: str,
    generated_by: str,
    catalog_version: str | None = None,
    is_family_excluded: Any = None,
    allowed_release_ids: frozenset[int] | None = None,
    max_endpoint_share: float = 0.15,
    max_bridge_share: float = 0.2,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Discover, select, and assemble a real Record Routes universe/rounds
    pair. Reuses `generate_round_pool` for discovery, then replaces its ordinal
    ids with content-derived stable ids and emits the Record Routes contract
    (mode, deterministic versions, art-free albums)."""
    rounds_json, diagnostics = generate_round_pool(
        graph,
        matched_albums,
        one_hop_target=one_hop_target,
        two_hop_target=two_hop_target,
        is_family_excluded=is_family_excluded,
        allowed_release_ids=allowed_release_ids,
        max_endpoint_share=max_endpoint_share,
        max_bridge_share=max_bridge_share,
    )
    if not rounds_json:
        raise RecordRoutesValidationError(
            "no eligible Record Routes paths were found between any matched albums"
        )

    for round_json in rounds_json:
        round_json["id"] = stable_route_id(round_json)

    seen = {r["id"] for r in rounds_json}
    if len(seen) != len(rounds_json):
        raise RecordRoutesValidationError("duplicate stable route id within one generation run")

    pool_version = record_routes_pool_version([r["id"] for r in rounds_json], snapshot_date)

    universe, rounds = build_rounds_v1(
        graph,
        matched_albums,
        rounds_json,
        snapshot_date=snapshot_date,
        generated_by=generated_by,
        pool_version=pool_version,
    )

    # Art-free: cover art is resolved by album id from the album-art registry
    # (ADR 0045), never embedded in this artifact. Strip BEFORE computing
    # artifact_version, so the version reflects the actually-published
    # (art-free) payload, not a pre-strip intermediate.
    for album in universe["albums"]:
        album.pop("cover_image", None)

    artifact_version = record_routes_artifact_version(
        albums=universe["albums"],
        rounds_json=rounds["rounds"],
        releases=rounds["releases"],
        artists=rounds["artists"],
        snapshot_date=snapshot_date,
    )
    for artifact in (universe, rounds):
        artifact["mode"] = RECORD_ROUTES_MODE
        artifact["provenance"]["catalog_version"] = catalog_version
        artifact["provenance"]["artifact_version"] = artifact_version

    return universe, rounds, diagnostics


def validate_record_routes_artifact(universe: dict[str, Any], rounds: dict[str, Any]) -> None:
    """Generation-time validation -- delegates to the same dependency-free
    checklist the Pi fleet and web build run
    (`networked_players_contracts.record_routes::record_routes_failures`), so
    the two can never drift."""
    failures = record_routes_failures(universe, rounds)
    if failures:
        raise RecordRoutesValidationError("; ".join(failures))
