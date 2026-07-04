# Graph core

Builds and queries the evidence-bearing music-credit graph over a parsed Discogs
one-hop dataset (`packages/catalog`'s `expand-one-hop` output), and generates the
album-centered challenge artifact (`data/contracts/challenge-v2.md`) consumed by
`apps/web`.

## Design: lazy, DuckDB-backed, query-per-hop

`graph.CreditGraph` does **not** materialize an in-Python adjacency structure. It
opens the one-hop Parquet tables as DuckDB views and answers every query --
neighbor lookup, path-finding, evidence retrieval -- with SQL. Path-finding is a
breadth-first search where each level is one SQL query joining the current
frontier against the credit table, rather than walking a pre-built graph object
in Python.

This is a deliberate choice, not an oversight: a one-hop corpus can hold hundreds
of thousands of credit rows, and the coordination host's working memory budget is
around 4GB. NetworkX or an explicit adjacency dict is the recorded revisit path if
a measured need appears (e.g. path lookups become a proven bottleneck under real
load) -- not something to build speculatively. See `graph.py`'s module docstring.

## Evidence rules (do not break)

- A positive linked `artist_id` is the playable identity (PAN); `anv` is
  per-credit display text only. `CreditGraph.artist_name` always returns the
  canonical name, never an ANV.
- A non-linked contributor (`is_linked=false`) never becomes a graph node, a path
  endpoint, or a `neighbors()` result -- it can only appear inside evidence rows
  (`credit_rows`).
- Discogs artist ID 194 ("Various") is excluded from the graph entirely -- a
  compilation placeholder, not an individual.
- `max_artists_per_release` bounds which releases *drive traversal* (a release
  crediting hundreds of artists shouldn't collapse the graph into a hub), but
  every release's full evidence remains queryable via `credit_rows`/`release`
  regardless of the cap.
- A credit is evidence of documented participation, never a claim of influence,
  friendship, or creative lineage (`docs/DATA_AND_RIGHTS.md`).

## Modules

- `graph.py` -- `CreditGraph` (open/neighbors/find_path/credit_rows/release/
  artist_name/stats), `Hop`, `EvidencePath`, `GraphError`.
- `challenge.py` -- `match_albums`, `build_challenge_v2`, `validate_challenge`,
  `ChallengeValidationError`; the album-centered challenge.v2 builder.
- `analysis.py` -- `rank_album_candidates`, the medium-term proxy-ranking
  mechanism for growing the editorial album list (`data/albums/README.md`).

## Testing

`packages/graph-core/tests/` uses real, tiny Parquet fixtures (written via the
catalog package's own PyArrow schemas, so a schema change to `parquet.py` is felt
here too) as the correctness oracle -- no live network, no real Discogs data. See
`conftest.py` for the standard fixture graph and its rationale.

## Dependency direction

`graph-core` must never import from `networked_players_catalog` -- the
dependency direction is catalog CLI -> graph-core only. Shared identity rules
(e.g. the non-individual artist ID set) are duplicated locally rather than
imported, so each package's evidence rules are self-contained and reviewable
without cross-package coupling.
