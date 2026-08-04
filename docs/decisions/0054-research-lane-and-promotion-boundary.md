# ADR 0054: A research lane, strictly separate from the public/publication lane

- **Status:** Accepted
- **Date:** 2026-08-04
- **Depends on:** [ADR 0018](0018-benchmark-results-local-only.md), [ADR 0043](0043-connection-guesser-corrective-slice.md) (publication-integrity discipline, via `PUBLIC_ARTIFACT_GROUPS`), [ADR 0046](0046-record-routes-productionization.md) (versioning-namespace non-collision precedent)

## Context

Phase 2 built a real public credit-discovery product: every artifact under
`apps/web/public/data/**` is validated, content-hash versioned, and
`PUBLIC_ARTIFACT_GROUPS`-registered. Phase 3 adds a different kind of work
— a personal research platform that builds bounded "topic corpora" for an
arbitrary subject (first real workload: Jamiroquai) from the full canonical
Discogs data and runs graph analytics over them. This output is
exploratory, private by default, and must never leak into the public
product just because a research run happened to produce something.

This ADR settles the boundary between the two lanes, since it's a real,
durable direction decision — not something to improvise inside
`packages/research`'s implementation.

## Decision

**Research lane**: everything `packages/research` produces lives under
`local/research/<topic-slug>/` — inheriting the project's *existing*
`local/` convention (one blanket gitignore rule already covers
`local/experiments/`, `local/analysis/`, `local/benchmarks/`,
`local/processed/`; no new gitignore entry was needed). Two levels of
identity, kept separate because corpus-building is the expensive step and
shouldn't repeat on every analysis re-run:

- `local/research/<topic-slug>/corpus/snapshot=<date>/` — a bounded,
  content-hash-versioned (`corpus_version`, via `canonical.py`'s existing
  `content_hash`) extract, built once per topic/seed/hop-tier combination.
- `local/research/<topic-slug>/runs/<run-id>/` — one run per
  `request.json` invocation against a (possibly cached) corpus: analysis
  outputs, a report, `findings.json`, `promotion_candidates.json`, a run
  manifest recording `corpus_version`, code commit, and which analyses
  ran.

**Publication lane**: unchanged. `apps/web/public/data/**`, a
dependency-free validator in `packages/contracts`, `PUBLIC_ARTIFACT_GROUPS`
membership, `canonical.py` versioning — the exact discipline every Phase
1/2 artifact already follows. Nothing in the research lane is ever
referenced from there.

**Promotion boundary — deliberately *not* a new `research promote`
command yet.** The existing promotion path already is: pick one research
output, write it up as its own slice (new contract module + dependency-free
validator + `PUBLIC_ARTIFACT_GROUPS` entry + an ADR if it's a real design
decision), human review, merge — the exact process `contributor_index` and
`pathfinding_graph` (Phase 2 Slices C/F) already went through. A `promote`
command becomes worth building only after a *second* real candidate proves
the pattern repeats, mirroring ADR 0039's own "extract a shared helper only
once a third surface needs it" discipline. Until then,
`promotion_candidates.json` is a structured, human-readable TODO list, not
an automated pipeline stage.

**`findings.json` typing**: every entry is `"kind": "fact"` (computed
directly by an analysis) or `"kind": "interpretation"` (a human- or
LLM-suggested reading, appended later, outside the automated pipeline).
The automated pipeline (`packages/research`) only ever writes `fact`
entries. This matters because community-detection and bridge-analysis
output is easy to over-read as a claim about real-world relationships —
tagging keeps a future promotion decision able to tell computed results
from suggested readings apart, and keeps the project's evidence-before-
inference discipline (never inferring influence/relationship from a
co-credit) intact in the research lane too, not just the public one.

**Topic corpora never read the private, collection-seeded one-hop corpus**
(`local/processed/discogs-onehop-v3/`). A topic corpus resolves its seed
fresh from the canonical parsed snapshot every time
(`resolve_artist_seed()`, a `DISTINCT`/`GROUP BY` query over the dataset's
own credit rows — no Artist-dump ingestion needed for this step). This
keeps a topic corpus's provenance clean of any dependency on the operator's
private collection, and sidesteps a real privacy question: whether a given
public artist appears in the operator's own collection-derived corpus is
itself collection-membership-adjacent information that should never leak
into a research run's provenance.

**Corpus builder reuses, not duplicates, `onehop.py`'s hardened
exclusions.** `packages/research/corpus.py` imports
`_NON_PLAYABLE_HUB_ARTIST_IDS` and `_performer_credit_sql` directly from
`networked_players_catalog.discogs.onehop` — the same real, hardened,
ADR-0026/0027-driven placeholder-artist and non-performer-role exclusions
the private one-hop corpus already uses, rather than re-deriving them.
`packages/research` is a new consumer, not `graph.py`/`challenge.py`/cohort
code, so the same import-a-private-helper pattern `role_taxonomy.py` and
`role_mode_candidates.py` already use for `eligibility.py`'s tokens applies
here too. The corpus builder's *output shape* also deliberately mirrors
`onehop.py`'s exactly (`table=releases`/`table=tracks`/`table=credits`/
`table=release_formats`/`manifest.json`) so a topic corpus is a drop-in
input to `networked_players_graph_core.graph.CreditGraph.open()` and every
other existing snapshot-shaped tool — no new graph-loading code needed.

**Hop tier defaults to 1, and 2 is not implemented yet.**
`docs/GRAPH_BENCHMARK_METHOD.md`'s own real measurement found a 500-album
2-hop ego network already balloons to touch most of the entire one-hop
corpus's edges — there is no comfortable medium tier between "small 1-hop"
and "basically everything." Rather than silently defaulting a topic
corpus's hop tier to something that might balloon the same way,
`build_topic_corpus()` raises a clear, typed error for any `hop_tier != 1`
until a real measured size check justifies going deeper (Phase 3's own
plan calls this out as a tripwire, not a guess).

**Request contract is JSON, not YAML.** No dependency was justified for a
schema this small and flat (`topic`, `seeds.artists`, `questions`,
`scope.hop_tier`, `analyses`) — Python's stdlib `json` module needs
nothing new. If a future request shape genuinely benefits from comments or
multi-line strings, moving to YAML is a small, isolated change; it wasn't
worth adding `pyyaml` as a dependency up front.

**`networked-players-research` is its own console script**, not folded
into `networked-players-catalog`'s CLI. `packages/platform` already
established the precedent that a genuinely separate bounded concern gets
its own `[project.scripts]` entry (`networked-players-platform`) rather
than growing the catalog CLI's already-large subcommand surface — Phase
3's research platform is exactly that kind of separate concern.

## Consequences

- `packages/research` becomes a new `uv` workspace member (alongside
  `contracts`/`platform`), depending on `networked-players-catalog` (for
  `onehop.py`'s exclusions) and `networked-players-contracts` (for
  `canonical.py`). `make setup` now runs `uv sync --all-packages ...`
  rather than plain `uv sync ...`, since nothing in the dependency graph
  points *at* `packages/research` the way `networked-players-catalog`
  points at `platform` — without `--all-packages`, a leaf workspace member
  never gets installed by a bare `uv sync`.
- Graph-library dependencies (`networkx`/`python-igraph`/`rustworkx`, Slice
  C) live behind a `research` extra on `packages/research`, not the base
  install — the request/corpus contract stays usable without pulling in
  three graph libraries nobody needs for Slice A/B.
- A privacy/boundary test suite (Slice D+) should assert no research-lane
  path ever appears in `apps/web/public/**` or `PUBLIC_ARTIFACT_GROUPS`,
  and that corpus-building never reads `local/processed/discogs-onehop-v3/`
  at all.

## Revisit trigger

If a second research finding ever needs promoting (after Slice G's first),
build the `research promote` command at that point — not before, and not
speculatively now.
