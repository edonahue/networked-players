# Contract: round seed spec v1

`data/rounds/round-<n>-seed-spec-v1.json` — a committed, **public** declaration of what an
expansion round is seeded from ([ADR 0072](../../docs/decisions/0072-campaign-atlas-lineage-approved-pool-collections.md)
section 7). Naming a theme approves no album; the approved pool does.

Not the round *runner's* spec ([`round-spec-v1.md`](round-spec-v1.md), which wires paths and policy
inputs). That one says how to rebuild; this one says what to look for. Validator:
`networked_players_contracts.round_seed_spec.round_seed_spec_failures` (dependency-free, runs on
1 GB Pis); CLI: `networked-players-catalog validate-round-seed-spec --spec <file>`.

## Shape

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int, `1` | |
| `round` | positive int | Must equal the runner spec's `round` (checked by the `theme-supply` stage). |
| `target_count` | positive int | Albums to add this round; must equal the runner spec's `target_count`. |
| `lane_shares_percent` | object | Exactly `theme`, `graph_value`, `coverage_repair`; non-negative ints summing to 100. `lane_quotas()` turns them into whole-album quotas by largest remainder. |
| `note` | non-empty string | |
| `themes[]` | non-empty list | Unique `name`s. |

Each theme (unknown keys are rejected):

| Field | Type | Meaning |
|---|---|---|
| `name` | non-empty string | A label only. |
| `seed_artist_ids` | list of positive ints | Public Discogs artist ids. Their billed masters are seeds. |
| `seed_master_ids` | list of positive ints | Public Discogs master ids. At least one of the two seed lists is non-empty (max 500 each). |
| `styles`, `genres` | list of strings | Optional exact Discogs tags. A shared-performer candidate must match one of them; seed masters are exempt. Empty means no tag filter. |
| `year_min`, `year_max` | int 1900..2100 or null | Decade bounds on the master's year (null = unbounded). Apply to every candidate. |
| `min_shared_performers` | int 1..20 | Stated, no default. Masters sharing at least this many distinct performers with the seed masters qualify. |
| `candidate_cap` | int 1..5000 | Stated, no default. Per-theme cap applied before the eligibility verdict. |

Only public ids and editorial labels belong here: no collection membership, scores or reviewer
identity.

## Supply semantics (`build-theme-candidates`)

One batched DuckDB query over the FULL parsed corpus for all themes. Performer overlap uses the
graph's own rule (ADR 0068: a performer-role token via `is_performer_role_sql`, or a billing scope).
Already-published and curated-excluded masters and the editorial non-studio genre/style set are dropped
in SQL; studio-album eligibility then runs through `master_eligibility`. Rows keep their reason when
ineligible. Output is private and refused unless git-ignored.

A synthetic example: `data/fixtures/round-seed-spec/synthetic-round-seed-spec-v1.json`. The real
Round 2 spec is not in the repository; see `data/rounds/README.md`.
