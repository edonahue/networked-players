# Artifact lineage contract (artifact-lineage-v1)

Declared lineage between the public artifacts under `apps/web/public/data/`
(ADR 0072 section 1, work package F1b). Implemented by
`networked_players_contracts.artifact_lineage` (dependency-free; the rule),
`networked_players_graph_core.lineage_inputs` (the builders' stamping helper)
and wired into `public_artifacts_failures` / `validate-public-artifacts`.

## Why content versions, not file hashes

Every artifact is re-formatted by Prettier after its builder writes it
(`docs/OPERATOR_SETUP.md`, "After any artifact build"), so a hash of file
bytes is stale the moment it is committed. The per-artifact `*_version`
fields hash semantic content through `canonical.content_hash` and survive
reformatting.

## The declaration

A builder that reads upstream public artifacts stamps
`provenance.inputs`: `{artifact_name: content_version}`, using the
`PUBLIC_ARTIFACT_GROUPS` names. A value is the upstream artifact's content
version at build time, or `null` when that artifact carried no content version
(for example a challenge built before `challenge_version` existed) -- never an
invented value. Artifacts that already have a `provenance` object (Connection
Guesser, Record Routes, challenge) gain a key inside it; the others
(album-art, credit membership, pathfinding graph, prominence, evidence
registry, contributor index, album hop distances, search index) gain a new
optional top-level `provenance` object holding only `inputs`. The validators
and the web graph loader accept the artifact with or without it.

`inputs` is provenance, not content: **no existing version formula hashes it**,
so adding it changes no published version.

## Dependency edges (read from the builders, not assumed)

| Artifact (group name) | Builder | Reads (public artifacts) |
| --- | --- | --- |
| `catalog` | `build-public-album-catalog` | none (approved pool and corpus roots are not public artifacts) |
| `album_credit_membership` | `build-album-credit-membership` | `catalog` |
| `pathfinding_graph` | `build-pathfinding-graph` | `catalog`, `album_credit_membership` |
| `challenge` | `build-challenge-from-dump` | `catalog` (`--albums`) |
| `record_routes` | `build-record-routes` | `catalog` |
| `connection_guesser` | `build-connection-rounds` | `catalog` |
| `album_art_registry` | `build-album-art-registry` | `catalog` |
| `evidence_release_registry` | `build-evidence-release-registry` | `catalog`, `challenge`, `record_routes`, `pathfinding_graph`, `album_art_registry` |
| `prominence` | `build-prominence` | `pathfinding_graph`, `evidence_release_registry` |
| `contributor_index` | `build-contributor-index` | `catalog`, `challenge`, `record_routes`, `evidence_release_registry` |
| `album_hop_distances` | `build-album-hop-distances` | `catalog`, `challenge`, `record_routes`; validated against `contributor_index`, so declared too |
| `search_index` | `build-search-index` | `catalog`, `contributor_index` |

`connection_daily_manifest` is built from the Connection Guesser rounds but is
append-only and frozen per generation (see classes below).

## Which field identifies each artifact's version

| Group | Version field | What it hashes (unchanged by this work) |
| --- | --- | --- |
| `catalog` | `catalog_version` | the catalog identity formula |
| `album_art_registry` | `art_version` | sorted art entries |
| `connection_guesser` | `provenance.artifact_version` | per-round content fingerprints, in order |
| `record_routes` | `provenance.artifact_version` | albums, rounds, releases, artists |
| `challenge` | `provenance.challenge_version` (new) | albums, artists, paths, releases, in order |
| `contributor_index` | `contributor_index_version` | per-contributor identity fields |
| `album_hop_distances` | `album_hop_distances_version` | (artist, album, distance) triples |
| `pathfinding_graph` | `pathfinding_graph_version` | node/edge/role arrays |
| `prominence` | `prominence_version` | its own metric arrays plus the graph version |
| `album_credit_membership` | `album_credit_membership_version` | albums and credit lists |
| `evidence_release_registry` | `evidence_release_registry_version` | its field arrays |
| `search_index` | `search_index_version` | sorted entries |

The table is `VERSION_FIELD_PATHS` in `artifact_lineage.py`; the edges are
`EXPECTED_INPUTS`. A test pins that the classes cover every
`PUBLIC_ARTIFACT_GROUPS` name.

## `challenge_version`

`provenance.challenge_version` =
`challenge-v2-<snapshot_date>-<content_hash of {albums, artists, paths, releases}, 12 hex>`.
It follows the Record Routes `artifact_version` rule ("hash everything
actually published, in published order"). `provenance` is deliberately
excluded: it holds `generated_by`, notes, `catalog_version` and build
parameters, none of which are content. The artifact has no `generated_at`; a
test proves a volatile `provenance.generated_at` would not move the version.
The validator recomputes it when present, and the builder re-stamps after
image enrichment (which edits `albums[].cover_image`). Optional: a challenge
without it is valid.

## The rule

For every `live` artifact that declares `provenance.inputs`:

- the value must be an object of `name -> version string | null`;
- a name that is not a known artifact is a failure;
- a non-null declared version must equal the upstream artifact's current
  version, else the failure (attributed to the downstream group) names both.

An artifact that declares no `provenance.inputs` **passes**.

### Classes

| Class | Members | Participates |
| --- | --- | --- |
| `live` | every built artifact in `PUBLIC_ARTIFACT_GROUPS` except those below | yes |
| `frozen` | `game/generations/*` (ADR 0041, ADR 0066) -- deliberately bound to old versions | no (never loaded by the rule) |
| `appended` | `connection_daily_manifest`, extended outside any rebuild | no |
| `source` | `approved_pool`, a hand-curated record, not a built artifact | no |

`source` is an addition to the three classes in ADR 0072: the approved pool is
neither rebuilt nor appended, and listing it as `live` would report it as an
unexplained gap.

### Stated limit

Artifacts committed before this contract declare no inputs and cannot be given
lineage retroactively: their parameters and non-committed inputs were never
recorded. They pass the rule. `validate-public-artifacts` reports which live
artifacts with upstream edges declare nothing, as data (not a failure):

```json
{"ok": true, "failures": {...}, "lineage": {"undeclared_inputs": ["album_art_registry", ...]}}
```

The list shrinks as each artifact is rebuilt; an empty list means every edge
is checkable. The rule does not require an artifact that declares inputs to
declare every expected edge.

## Build parameters for the Connection Guesser pool

`build-connection-rounds` now stamps `provenance.build_parameters`
(`one_hop_target`, `two_hop_target`, `max_endpoint_share`, `max_bridge_share`)
and inherits them via `--previous-connection-universe <game/universe.v1.json>`,
using the same `build_parameters.py` mechanism and precedence as
`build-record-routes` (explicit flag, then previous artifact, then the
defaults 300/200/0.15/0.2). It prints the resolved values and their source to
stderr and in its JSON summary. The block is optional in the validator.

## What the rule reports besides failures

`validate-public-artifacts` prints two lists as data under `lineage`, neither of which fails
the run:

- `undeclared_inputs` — live artifacts with upstream edges that declare no `provenance.inputs`
  at all (every artifact built before this contract).
- `partially_declared_inputs` — artifacts that declare inputs but omit one or more of the
  expected edges above, with the omitted names. An omitted edge is not being checked.

A `provenance` that is present but malformed is a failure, never "undeclared": it must be an
object, and for the artifacts that gained a top-level `provenance` only to carry lineage
(album art, credit membership, pathfinding graph, evidence registry, prominence, contributor
index, hop distances, search index) it may contain nothing but `inputs`.

## Fleet ordering

Per-artifact validators on fleet workers come from the `networked_players_contracts` package
in each worker's **release venv** (`~/.local/share/networked-players/platform/releases/<commit>/venv`),
which `make platform-deploy` creates per commit from the wheels `make platform-build` packaged.
(`equip-workers.yml` installs contracts into a different, legacy `worker-venv` used only by old
copied job bodies; reinstalling there does not change what `artifact.validate` runs.) A worker
whose release predates this contract rejects a rebuilt artifact that carries `provenance`
("unexpected top-level keys"). The package version is a constant, so it cannot tell a stale
worker from a bad artifact; the validation report (`platform-validation-report-v2`) therefore
records `contracts_version`, `contracts_digest` (a content digest of the contracts package that
ran), `runtime_digest`, the worker's built `runtime_commit`, `worker_id` and `attempt` (ADR 0073,
Campaign Atlas work package I1). **Build and deploy a release containing the current contracts to
every worker before the first rebuild that stamps lineage is validated on the fleet**, and confirm
with `make platform-status` that every worker's contracts digest says `match` against the
checkout; that command measures the release venv, which is the one that matters. A fleet-wide
failure whose reports carry a `contracts_digest` that differs from the checkout's is a staleness
problem, not an artifact problem.
