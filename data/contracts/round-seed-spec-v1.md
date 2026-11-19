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
| `max_masters_per_seed_artist` | int 1..5000 | Stated, no default. At most this many ELIGIBLE masters per seed artist enter the pool, so a theme surfaces the scene rather than one discography. It counts only seed-artist-route masters, grouped by the seed artist they were found under (a collaboration counts under the lowest seed artist id); it does NOT count explicit `seed_master_ids` (exempt: they neither use up nor get cut by the cap), shared-performer candidates, or ineligible masters. A master cut by the cap never re-enters through the overlap route. |
| `min_overlap_share_percent` | int 0..100 | Stated, no default. Pool slots reserved for shared-performer (overlap) candidates: `ceil(candidate_cap * share / 100)`, after explicit seed masters (exempt from the quota, always kept up to the cap). Slots the seed-artist route does not use also go to overlap. If fewer ELIGIBLE overlap candidates exist, the pool is smaller and the summary reports `overlap_shortfall`; it is never padded with extra seed-artist masters. |

Only public ids and editorial labels belong here: no collection membership, scores or reviewer
identity.

## Supply semantics (`build-theme-candidates`)

One batched DuckDB query over the FULL parsed corpus for all themes. Performer overlap uses the
graph's own rule (ADR 0068: a performer-role token via `is_performer_role_sql`, or a billing scope).
Already-published and curated-excluded masters and the editorial non-studio genre/style set are dropped
in SQL; studio-album eligibility then runs through `master_eligibility`. Pool composition per theme: the SQL gates produce a pre-cap considered set (all seed-route
masters; the best `10 * candidate_cap` overlap candidates by shared performers, with the true total
and any truncation reported). Eligibility (including the bounded format classification) is decided
over that set, and the per-artist cap, overlap reservation and `candidate_cap` then apply to
ELIGIBLE masters only, so an ineligible live album or box set never pushes an eligible master out.
Within each route candidates rank deterministically by distinct shared performers (descending),
then master id. Ineligible considered masters stay in the output with their reason, outside the
cap accounting. Each theme summary reports `considered_count`, `pool_size`/`eligible_count` (the
selected, eligible pool), `route_mix` (selected, per route), `ineligibility_reasons`,
`max_masters_per_seed_artist_selected`, `max_masters_per_billed_artist_selected` (the billed-artist
maximum can exceed the per-seed-artist cap because overlap candidates are not capped),
`overlap_quota`, `overlap_shortfall`, `dropped_seed_masters` and `review_flag_counts`.
Each row carries advisory `review_flags` (`live_title`, `compilation_title`: the classifier's own
title patterns applied to the master and main-release titles). They change no eligibility; they
surface in the review packet so the owner can reject such albums quickly. Rows keep their reason when
ineligible. Output is private and refused unless git-ignored.

A synthetic example: `data/fixtures/round-seed-spec/synthetic-round-seed-spec-v1.json`. The real
Round 2 spec is not in the repository; see `data/rounds/README.md`.
