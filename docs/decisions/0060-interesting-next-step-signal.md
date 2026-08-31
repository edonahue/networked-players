# ADR 0060: `interesting_next_step` — a role-disjoint, anti-hub contributor signal

- **Status:** Accepted
- **Date:** 2026-08-16
- **Depends on:** [ADR 0048](0048-contributor-index-and-pages.md), [ADR 0054](0054-research-lane-and-promotion-boundary.md), [ADR 0059](0059-recommended-route-selection.md)

## Context

Phase 6 asked whether graph-derived intelligence — degree, betweenness,
community detection, or some "interesting next step" ranking — could make
exploration more compelling, with an explicit instruction to reject or defer
any candidate signal that turned out unstable, trivial, hub-dominated, or
uninterpretable, and to never ship an "AI magic score."

Two real constraints bound the design space before any measurement:

1. **The public contributor index is deliberately built from already-published
   artifacts only** (`challenge.v2.json`, `routes/{universe,rounds}.v1.json`,
   the evidence-release registry) — never a fresh full-corpus query
   (`contributor-index-v1.md`'s own revisit trigger). Betweenness centrality
   and Leiden community detection (`packages/research/graph_analysis.py`)
   both require `igraph` over the full one-hop corpus and are deliberately
   local-only/interactive per ADR 0054 — never dispatched to the Pi fleet,
   never promoted to a public artifact. Reusing them here would mean either
   violating that boundary or silently redefining what "already-published"
   means for this contract. Neither is acceptable without a real, separate
   ADR of its own.
2. **Raw degree is exactly the signal ADR 0059 already measured and
   rejected** for Connect's old route scorer: it correlates with fame, so
   "most connected neighbor" would always point toward the same handful of
   hub contributors (Quincy Jones, session legends) — the opposite of an
   *exploration* aid.

Given those two constraints, any candidate had to be computable entirely
from fields already in the published index (`role_categories`,
`connection_count`, `neighboring_contributor_ids`), and had to avoid
degree-based ranking by construction, not by a tacked-on penalty.

**Measurement, against the real committed artifact (549 contributors,
`contributor-index-v1-20260601-...`), before building anything:**

- `connection_count` is heavily skewed even within a contributor's own
  neighbor list: median 2, max 52. 366 of 549 contributors (67%) have only
  1–2 neighbors at all — for these, there is almost nothing to *rank*
  either way, a real ceiling on how much value any per-neighbor ranking can
  add for the common case.
- 246 of 549 contributors (45%) carry more than one `role_categories` value
  themselves — real, substantial diversity to work with, not a rounding
  error.
- Restricting to contributors with ≥2 neighbors (545 of 549): 376 (69%) have
  at least one neighbor whose `role_categories` set is entirely disjoint
  from their own — a real, common, non-trivial condition, not a rare edge
  case. 169 (31%) have no such neighbor — a real, substantial "nothing to
  suggest here" population, which the design keeps honest rather than
  papering over.

## Decision

Add one new field per contributor, `interesting_next_step`, computed
entirely within `contributor_index.py` from data already in the same
artifact:

```json
{"artist_id": 673305, "reason": "credited in a different kind of role than this contributor"}
```

or `null`.

**Selection, in order:**

1. Filter this contributor's own `neighboring_contributor_ids` (already
   capped at 20, already computed) to those whose `role_categories` are
   **entirely disjoint** from this contributor's own — a real structural
   fact (this person is credited in a genuinely different kind of role),
   never an inferred claim about interest, quality, or importance.
2. If none qualify, `interesting_next_step` is `null`. Never a fabricated
   pick just to fill the field — the 31% "nothing to suggest" population
   above is real and stays visibly real.
3. Among qualifying candidates, break ties toward the **lowest**
   `connection_count` — the deliberate anti-hub choice: this can only ever
   favor a lesser-explored contributor over a more-connected one, never the
   reverse. `artist_id` is the final, fully deterministic tie-break.

`reason` is a single fixed, factual string — not a template with variables,
not free text, not an LLM output. There is exactly one reason this field is
ever populated, so there is exactly one sentence describing it.

**Rejected for this artifact, explicitly, with reasoning:**

- **Betweenness centrality / community detection** — real, useful, already
  implemented in `packages/research`, but require the private full corpus
  and `igraph`, which the published contributor index must never depend on
  (see Context). Extending ADR 0054's boundary to promote either into a
  public artifact is a separable, bigger decision this ADR does not make.
- **Raw "most connected neighbor"** — measured, real hub bias, the same
  failure mode ADR 0059 already found and fixed once; reintroducing it here
  for a different feature would be repeating a known mistake, not a fresh
  design.
- **Any learned/weighted/multi-factor score** — "never ship an AI magic
  score" per the original brief. A single boolean gate (role-disjoint or
  not) plus one deterministic, documented tie-break is the entire ranking;
  there is no blended weight to tune, second-guess, or silently drift.

## Consequences

- `_CONTRIBUTOR_KEYS` (contracts) and the contract doc
  (`data/contracts/contributor-index-v1.md`) both require
  `interesting_next_step` on every entry — `null` is a valid, required
  value, not an omitted key. `schema_version` stays `1`: this is a plain
  additive field on an artifact with no prior schema-version split to
  preserve, unlike the evidence-release registry's real v1/v2 optional-field
  precedent.
- `interesting_next_step` is deliberately **excluded** from
  `contributor_index_version`'s identity hash, matching the existing
  precedent for `connection_count`/`neighboring_contributor_ids`
  /`decade_activity`/`role_text_examples` (only `artist_id`/`name`/
  `role_categories`/`albums`/`evidence` are load-bearing identity; this is a
  lookup index, not a fingerprinted content pool).
- The real committed artifact was regenerated
  (`contributor-index-v1-20260601-c57aee819b6f`): 379 of 549 contributors
  (69%) now carry a real `interesting_next_step`; 170 (31%) carry `null`,
  matching the pre-build measurement almost exactly.
- PR 6-10 surfaces this field in the UI (a small "worth a look" callout
  alongside the existing neighbor list, never a replacement for it — every
  neighbor stays visible, this only highlights one). Not yet surfaced
  anywhere as of this PR.

## Validation

`packages/graph-core/tests/test_contributor_index.py`: a role-disjoint
neighbor is picked over a same-category one; a contributor with no
role-disjoint neighbor gets `null`; a dedicated tie-break fixture (two
disjoint-role candidates with different `connection_count`) proves the
lower-`connection_count` one wins, not the higher. `packages/contracts/
tests/test_contributor_index_contracts.py`: `interesting_next_step` is
required (missing key rejected), `null` is valid, an object must have
exactly `{artist_id, reason}`, `artist_id` must resolve to both a published
contributor *and* one of this contributor's own `neighboring_contributor_ids`,
`reason` must be non-empty. `make check`'s `validate-public-artifacts`
passes against the real regenerated artifact.

## Addendum (2026-08-31): excluding a background-engineering-only tie

The owner asked to de-emphasize connections whose only documented evidence
is a background-engineering credit (Mastered By/Recorded By/Mixed By) --
see this repo's site-copy/background-connections work. Applied literally
to this field, the original Decision's role-disjointness gate has a real
gap: two contributors can have entirely disjoint `role_categories` (so
they pass step 1 above) purely because the ONLY hop connecting them is a
shared mastering/mixing/recording credit -- role-disjoint is a true
structural fact about their `role_categories`, but it does not mean the
underlying connection itself is substantive. Surfacing that pair as
"worth a look" would point a reader at exactly the kind of thin,
likely-coincidental tie this repo's background-connections work exists to
de-prioritize elsewhere (route ranking, Explore dimming, contributor/album
page ordering).

**Amended selection**: step 1's candidate filter gains a second condition,
evaluated alongside role-disjointness, not after it. A neighbor is
excluded when EVERY hop connecting this contributor to that neighbor (across
every path/round where they co-occur) is background-engineering-only on at
least one side -- tracked in `contributor_index.py`'s `record_hop` via a
per-pair `background_only_by_pair: dict[frozenset[int], bool]`, AND-reduced
across every hop seen between that pair (so a pair that ALSO shares even
one real substantive-role hop, on a different release, is never excluded --
only a pair whose ENTIRE shared evidence is background-only is). This
changes what `null` can mean: **`null` no longer implies "no role-disjoint
neighbor exists"** -- it can now also mean "a role-disjoint neighbor exists,
but every connection to them is background-engineering-only, so none of
them qualifies as a genuinely interesting next step." Both are still the
same honest answer this field has always given: nothing here is worth a
special callout, never a fabricated pick to fill the slot.

The real committed artifact was regenerated
(`contributor-index-v1-20260601-<hash tracked in the addendum PR>`) under
this amended rule.

## Revisit trigger

If a future measurement shows the role-disjoint condition degrading (e.g. a
corpus regeneration collapsing role diversity, or the 67%-have-≤2-neighbors
ceiling above making this signal effectively invisible in practice once
surfaced in the UI), revisit before extending it further. If a real product
need for betweenness- or community-based ranking emerges, that requires
extending or superseding ADR 0054's research/publication boundary
explicitly, as its own decision — never a silent widening of this one.
