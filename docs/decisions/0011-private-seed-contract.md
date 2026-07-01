# ADR 0011: Private seed contract -- release-IDs-only JSON, stored under data/private/

- **Status:** Accepted
- **Date:** 2026-07-01

## Context

ADR 0005 already committed to "a private local collection export supplies release IDs
only as the initial seed," and `docs/DATA_AND_RIGHTS.md` states "the first adapter should
reduce a local export to release IDs before catalog processing" -- but no concrete file
format, module, or storage location existed until now. BUILD_PLAN.md's Milestone 4 flagged
this as a "durable contract" needing an ADR once chosen, and named `local/` as a candidate
location; `docs/DATA_AND_RIGHTS.md`'s "Private seed" data-class terminology points more
precisely at `data/private/`, which also already carries a hard agent-level `Read` deny
(`.claude/settings.json`) in addition to `.gitignore` protection. The user's real Discogs
collection export (the standard discogs.com "Export Collection" CSV) was available this
session, making this the first real vertical-slice input the project has had.

## Decision

Define `SeedManifest` (`packages/catalog/src/networked_players_catalog/discogs/seed.py`):
a single JSON object with `seed_version`, `source`, `imported_at`, and a deduplicated,
sorted `release_ids: list[int]` -- nothing else. The `import-seed` CLI command
structurally reads only the `release_id` column of a source CSV, so no account-linked
field ever has a code path into the seed. Store the real seed under `data/private/`, not
`local/`, matching `docs/DATA_AND_RIGHTS.md`'s naming and inheriting the existing
agent-Read-deny rule as defense in depth. Synthetic fixtures are tracked under
`data/samples/`.

## Consequences

Milestone 5 (one-hop expansion) has a stable, minimal input format to build the
artist-ID frontier from. The contract intentionally omits any existence check against a
real catalog dataset -- `import-seed` succeeds even if a release ID matches nothing yet,
since that cross-reference is Milestone 5's job. Because the real seed lives under
`data/private/`, any future agent session is blocked from reading it at the
tooling-permission layer, not just `.gitignore` -- correct for privacy, but means a human
operator must inspect the real seed file directly if something needs debugging.

## Validation

`import-seed` run against the synthetic fixture produces a `SeedManifest` whose
`release_ids` matches the fixture's known IDs exactly; a dedicated test asserts the output
JSON contains no trace of any non-`release_id` column value from a fixture row that
populates every column. `git check-ignore -v data/private/discogs-seed.json` confirms the
real seed is excluded from version control.

## Revisit trigger

Revisit if Milestone 5 discovers the seed needs more than a bare release-ID list (a new
`seed_version`, not a silent field addition). Revisit if a second private-data input type
is ever added, to decide whether it shares this contract.
