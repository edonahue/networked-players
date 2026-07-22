# ADR 0039: A fail-closed performer allowlist, layered only for game rounds

- **Status:** Accepted
- **Date:** 2026-07-19
- **Extends:** [ADR 0035](0035-track-scoped-credit-edges.md) without modifying it

## Context

The real-data launch's flagship game (Connection Guesser / Connection of the Day)
needs a stricter rule than the album/cohort surfaces: a round's evidence must show
that both people actually **performed** — sang or played an instrument — not merely
that they were both credited on a release. `credit_edges_sql`'s existing role rule
(`_NON_COLLABORATIVE_ROLE_TOKENS`, ADR 0035) is a **denylist** deliberately tuned the
other way: it keeps a bare `Producer` or `Mixed By` credit edge-eligible, because for
the album challenge and the cohort pipeline "did these two people plausibly share a
session" is the right question, and narrowing that would silently regress two
surfaces the game does not own.

Building the game's rule as a second denylist, or as an option flag on
`credit_edges_sql` itself, would either (a) require the game to enumerate every
non-performer role Discogs uses, an open-ended and easy-to-miss set, or (b) risk a
future edit to the shared denylist accidentally tightening the album/cohort graph
too. Both risks are avoidable by asking a narrower question a different way.

## Decision

Add `packages/graph-core/.../eligibility.py`, a standalone module never imported by
`graph.py`, `challenge.py`, or the cohort pipeline — only by round generation
(`rounds.py`, `rounds_generator.py`). It exports `is_performer_role(role_text)` and a
SQL mirror `is_performer_role_sql(role_column)`, kept in sync by
`test_is_performer_role_matches_the_sql`.

Unlike `credit_edges_sql`'s denylist, this is an **allowlist**: `_PERFORMER_ROLE_TOKENS`
enumerates ~80 explicit instrument/vocal tokens (voice, fretted/bowed strings,
percussion/keys, brass, woodwind), matched after the same bracket-stripping
normalization the denylist uses (`Guitar [12-String]` still matches `guitar`). Any
role text that doesn't match — including `NULL`, a bare release-artist billing with
no role text at all — is **excluded**, the opposite default from the denylist, where
an unrecognized role stays edge-eligible. Billing is not proof of performance.

A round's hop (`rounds.py::build_round_hop`) is only built when **both** artists have
at least one eligible role on the shared release; otherwise the whole path is dropped
for game purposes, even if it remains valid evidence for `challenge.v2.json`
(`build_round_from_path`'s docstring states this explicitly). This is deliberate
divergence, not a bug: a path can be good album evidence and bad game evidence at
the same time.

The set starts deliberately narrow. It is meant to be extended only by adding tokens
after reviewing real unmatched role strings, never by relaxing the
default-excluded posture — an unrecognized future role text should keep failing
closed, not open.

## Consequences

- Album/cohort connectivity is completely unaffected: `credit_edges_sql` is untouched,
  and this module is not on any import path that reaches it.
- The game's rounds pool is real-measured smaller than a denylist-based rule would
  produce (see `docs/DATA_SIZING.md`'s "Real-data launch" section: 72 one-hop / 100
  two-hop rounds against a 140-album backbone) — an honestly reported, expected
  consequence of asking a strictly narrower question, not a defect to paper over.
- A two-hop round needs *both* hops to independently pass this gate on top of the
  studio-album format policy and relationship exclusion, which compounds the
  narrowing at two-hop scale specifically — the likely reason two-hop yield tracked
  closer to the plan's target range than one-hop yield did.
- Expanding the token set later is a config-only change reviewable by a human reading
  a flat frozenset, the same auditability property `placeholder_artists.json`
  (ADR 0035) already established for the denylist side.

## Validation

`packages/graph-core/tests/test_eligibility.py` covers the Python/SQL parity fixture
(`test_is_performer_role_matches_the_sql`), bracket-stripping, comma-separated
multi-role text, and the `NULL`-excluded default. `test_rounds.py` covers
`build_round_hop` returning `None` when either side lacks an eligible role, even
when the underlying credit would be a valid `challenge.py` edge.

## Revisit trigger

If real gameplay data shows a common, legitimately-performing role text this list
misses (visible as an unusually high drop rate in round generation diagnostics, or
via the CLI's `--dump-unmatched-roles` diagnostic), extend
`_PERFORMER_ROLE_TOKENS` directly — that is the intended, low-risk revision path.
Revisit the allowlist-vs-denylist split itself only if a second surface ever needs
this same narrower definition; a third fail-closed rule layered the same way is a
signal to extract a shared helper, not to relax `credit_edges_sql`'s denylist.
