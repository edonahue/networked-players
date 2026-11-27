# ADR 0075: One per-credit "is this a performing credit?" classifier

- **Status:** Proposed (draft PR; changes no gate and no published artifact)
- **Date:** 2026-11-27
- **Builds on:** [ADR 0068](0068-performer-only-public-graph.md) (performer-only graph),
  [ADR 0047](0047-role-taxonomy-as-a-third-orthogonal-classification-layer.md) (role taxonomy),
  [ADR 0039](0039-performer-allowlist-layered-for-game-rounds.md)

## Context

ADR 0068's per-credit performer rule exists in three places: `graph.credit_edges_sql`
(SQL), `relationship_pool.performer_qualifying_credit_sql` (SQL), and inline inside
`pathfinding_graph.edge_eligible_membership_artist_ids` (Python, per artist). There is no
named Python predicate that takes one credit row and answers "does this document a
performance?". Consumers that work credit-by-credit over `credit-membership.v1.json`
(a duet-lab prototype that links albums only by shared performers, weighted by
`1 / log2(1 + albums the performer appears on)`) had to write their own regex, which
diverged from NP's measured token set in both directions.

The allowlist is fail-closed and token-exact, which is correct for the public graph but
misses real, unambiguous instrument/vocal strings it has never been taught
("Harmony Vocals", "Pedal Steel Guitar", "Contrabass", "Handclaps", "Singer").

## Decision

Add `packages/graph-core/.../performer_credit.py` with `is_performing_credit(credit)` and
`classify_performing_credit(credit)` (verdict + `basis`). The rule, in order:

1. `graph.edge_ineligible_role` → not performing (denylist and quotation roles such as
   `Performer [Sample]`), whatever the scope.
2. `release_artist`/`track_artist` scope → performing, including a NULL role.
3. Any component that is an `eligibility._PERFORMER_ROLE_TOKENS` token → performing.
4. Only components NP does not recognize at all (no performer token, no `role_taxonomy`
   category, not an ADR 0068 deliberate exclusion) fall through to the prototype's regex
   heuristic.

Components are split on commas outside brackets, then bracket-stripped.

**This module is not a gate.** `graph.py`, `pathfinding_graph.py` and every published
artifact builder keep the ADR 0068 token allowlist. A regex-fallback hit is a *candidate*
token for that allowlist, reviewed through `classify-roles`, not a silent widening.

### Judgment calls

- **`Arranged By` is not performing**, even when the arranger also played: the arranging
  credit does not say they played. A separate instrument credit on the same release is
  what counts (and usually exists).
- **`Programmed By`, `Programming`, `Drum Programming`, `Drum Machine` are not
  performing.** Drum programming arguably is performance, but ADR 0068 measured and
  excluded "Programming"/"Programmed By"; the classifier follows it rather than overturning
  it through a regex. `Sampler` likewise stays excluded (ADR 0068: ambiguous).
- `Conductor`, `Orchestrated By`, `Cover`, `Leader` stay excluded per ADR 0068.
- **Quotation roles are never performing** (the unmodified prototype counted
  `Performer ["Walk On By" Samples]` as a performer: 31 quotation-role rows in the published
  catalog).
- **A role regex is a heuristic.** It is limited to strings NP has not classified, and its
  hits are listed for review rather than trusted.

### Measured agreement (published `credit-membership.v1.json`, 217 albums, 16,592 credits)

| Rule | Performing credits | Album–artist pairs |
| --- | ---: | ---: |
| ADR 0068 canonical | 8,197 | 4,475 |
| Prototype regex | 8,295 | 4,460 |
| This classifier | 8,402 | 4,545 |

Canonical and prototype agree on 8,017 performing credits and disagree on 458 rows (149
distinct role/scope pairs). The classifier's basis breakdown: allowlist 7,888, billing 311,
regex fallback 203 (39 distinct components, all reviewed as real instrument/vocal credits),
ineligible role 3,960, not performing 4,230.

### A canonical parsing defect found on the way

`is_performer_role` splits on every comma, including commas inside brackets. That misses
`Synthesizer [Mini-moog, Arp]` and `Soloist [Solos, Drums]`, and falsely accepts
`Arranged By [Rhythm, Synthesizer, Vocals]` (5 rows in the catalog). This ADR does **not**
change `is_performer_role`; fixing it changes graph edges and needs its own measured
change.

## Consequences

Per-credit consumers have one tested predicate that agrees with the public graph except
where it adds reviewed-unrecognized instrument strings or corrects the bracket-comma split.
The two rules can now drift; `test_superset_of_canonical_rule_without_bracket_commas`
pins the intended relationship.

## Validation

`packages/graph-core/tests/test_performer_credit.py`: the required performing /
non-performing role cases in both credit scopes, billing and NULL-role scopes, ADR 0068
deliberate exclusions, quotation roles, bracket-aware splitting, superset-of-canonical, and
the agreement report on a synthetic membership.

## Revisit trigger

Promote regex-fallback strings into `_PERFORMER_ROLE_TOKENS` after a `classify-roles` run on
the full corpus (then the fallback shrinks). Revisit if the bracket-comma split in
`is_performer_role` is fixed, or if a consumer needs this predicate to gate published data.
