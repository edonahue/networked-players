# Research album-projection clustering method (Campaign Atlas S1 / E1)

Method only. This document records what is measured and how to reproduce it; it
contains no results and decides nothing. The gate it feeds is ADR 0072 section 6
(`docs/decisions/0072-campaign-atlas-lineage-approved-pool-collections.md`); the
earlier performer-graph denial it does not touch is ADR 0070. Real output is
research-lane material (ADR 0054) and stays local and git-ignored; this
repository commits no study output. The study reports counts and graph
statistics only, never elapsed time or memory (ADR 0018).

## What is measured

ADR 0070 denied Leiden on the performer graph because album anchors are never
adjacent. The untested object is the **album projection**: records as nodes, an
edge between two records when they share credited performers.

Inputs are committed public artifacts only: the published pathfinding graph
(`apps/web/public/data/pathfinding/graph.v4.json`, read through
`route_quality.load_published_graph`) and the canonical catalog
(`apps/web/public/data/catalog/albums.v1.json`). No private or local corpus.

1. **Performer set.** For each catalog album, the neighbours of its virtual
   album-anchor node in the published graph (other anchors are never counted).
   An album with no anchor, or an anchor with no neighbours, is a node with an
   empty performer set (it stays in the denominator and ends up a singleton).
2. **Edges.** Albums A and B are linked when they share at least `min_shared`
   performers (default 2). With `include_same_artist` false (default), pairs
   whose albums have the same primary `artist_id` are excluded -- a band's own
   albums share a lineup by construction. `weight` = sum over shared performers
   `p` of `1 / ln(1 + albums(p))`, where `albums(p)` counts all catalog albums
   `p` appears on (an Adamic-Adar style hub discount).
3. **Clustering.** igraph Leiden, modularity objective, weighted, `resolution`
   (default 2.0), over a fixed seed list (default seeds 0..9, `random.seed`
   before each run as igraph requires). Iterations are capped at 50 (igraph's
   run-until-stable mode can fail to terminate on tiny graphs). The best run is
   the one with the highest weighted modularity at the study's own resolution;
   ties go to the lexicographically smallest canonical membership. Clusters are
   canonically ordered (size descending, then smallest member), so identical
   inputs and parameters yield byte-identical JSON.
4. **Reported measurements.** Cluster count and size distribution; largest
   cluster share of all albums; **coverage** = share of albums in clusters of at
   least 4 albums spanning at least 3 distinct primary artists; modularity Q
   (always computed at resolution 1, weighted); stability; per qualifying
   cluster: albums (sorted by year), internal density (unweighted edges over
   possible pairs), year span, and bridge players (performers on at least 2 of
   the cluster's albums, top 8 by count).
5. **Null models.** (a) `null_model`, as specified: the projection graph
   rewired with its degree sequence preserved and its weights permuted
   (`null_count`, default 20), same clustering procedure, giving null mean, std
   and the z-score of the real Q. (b) `bipartite_null_model`, added because (a)
   is biased towards passing: the album-performer incidence is rewired with
   double-edge swaps (album sizes and performer album-counts preserved),
   re-projected with the same parameters and clustered the same way. Rewiring
   the projection itself destroys the clique structure that every bipartite
   projection has (a performer on k albums makes a k-clique), so structureless
   sharing can score a large z against (a) while scoring near zero against (b).
   Both are reported; neither is silently preferred.
6. **Stability.** Mean and min adjusted Rand index over all pairs of seed runs;
   and under edge perturbation (drop a random 10% of edges, 10 repeats, the same
   seeded procedure on the thinned graph) against the reference partition,
   compared on nodes that still have an edge in both graphs.

## Gate block (data, not a decision)

The `gate` block lists each numeric criterion of ADR 0072 section 6 with
threshold, measured value and pass/fail: largest cluster at most 25% of albums;
coverage at least 40%; modularity above the null. ADR 0072 says "clearly above";
this study operationalises that as z >= 3 against each null, which is the
study's choice rather than an ADR number. The fourth criterion, that the owner
finds at least 7 of 10 sampled clusters musically legible, is a human judgement:
`owner_legibility_review` is always the string `"pending"` and is never computed
or inferred. The Markdown rendering lists the qualifying clusters so a person
can judge them.

## Sensitivity sweep

`research-album-projection-sweep` repeats the measurement for `min_shared` in
{1, 2, 3} x `resolution` in {1, 2, 3} and writes a compact table, so a reader
can see whether a result is an artefact of one parameter choice.

## Reproducing from a clean checkout

```sh
make setup        # installs the optional 'graph' extra (igraph)
D=local/analysis/campaign-atlas/e1-album-projection
uv run networked-players-research research-album-projection --output $D/study.json
uv run networked-players-research research-album-projection-sweep --output $D/sweep.json
```

Each command writes the JSON and a Markdown rendering beside it (`.md`). Useful
options: `--min-shared`, `--resolution`, `--seeds` (count), `--null-count`,
`--perturbation-repeats`, `--include-same-artist`, `--graph`, `--catalog`. The
CLI refuses any output path under `apps/web/public/`. `local/` is git-ignored.
The code is `packages/research/src/networked_players_research/album_projection.py`;
tests use synthetic fixtures only.

## Known limits

- Performer sets come from the published graph, which already applies the
  performer-only edge relation (ADR 0068); a different credit policy would
  change the projection.
- The catalog is the 217-album public catalog, not a sample of all records, so
  coverage and cluster shapes describe this catalog's selection effects too.
- Leiden at resolution above 1 can split a uniform clique into singletons; the
  resolution is a parameter to read alongside the sweep, not a tuned optimum.
- Z-scores with 20 null draws are coarse; they are a screen, not a p-value.
