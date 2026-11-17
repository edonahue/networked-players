# Round spec v1

The declarative input to `networked-players-catalog round <plan|run|verify>` (ADR 0072
section 3; `packages/catalog/src/networked_players_catalog/round_runner.py`). One committed JSON
file per round, `data/albums/rounds/round-<n>.json`. Only a synthetic template,
`data/albums/rounds/example-synthetic-round.json`, exists today; no real round spec has been
written. If this note and the code disagree, the code wins.

A spec records paths **as given** (relative paths resolve against the working directory).
The runner checks that stated paths exist; it never reads `data/private/` content itself, only
passes the path to the builder that already consumes it. Never put secrets in a spec.

## Fields

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `round` | positive integer; passed as `--expansion-round` |
| `target_count` | positive integer; passed as `--target-count` |
| `themes` | list of label strings; labels only, naming a theme approves no album |
| `generated_at` | explicit ISO datetime with UTC offset, passed to every builder as `--generated-at` (never the wall clock) |
| `planned_merge_date` | ISO date the round PR is planned to merge |
| `daily.cutover_lead_days` | integer >= 1; cutover date = `planned_merge_date` + this |
| `daily.new_generation_id` | id of the new daily-manifest generation; must not already exist |
| `daily.days` | dates scheduled under the new generation |
| `paths.previous_artifacts_dir` | read-only snapshot of the published `apps/web/public/data` (carry-forward, inherited parameters, continuity baseline). Must differ from `output_dir` |
| `paths.output_dir` | where stages write; a directory named `data` (real target `apps/web/public/data`) |
| `paths.work_dir` | scratch for `stage-results.json` and `report.md`; not inside `output_dir`; git-ignored in practice (`local/`) |
| `inputs.*` | see below |
| `parameters.<builder>.<name>` | optional explicit overrides: `challenge` (`max_hops`, `max_frontier_expansion`), `record_routes` and `connection_rounds` (`one_hop_target`, `two_hop_target`, `max_endpoint_share`, `max_bridge_share`). Anything omitted or `null` is inherited from the previous artifact's `build_parameters` |

## Inputs: no silent defaults

Every key of `inputs` must be present. Each is either a path string, or
`{"path": null, "reason": "<non-empty text>"}` when this round genuinely does not use it.

`onehop_root`, `masters_root`, `release_format_policy`, `studio_album_exclusions`,
`candidates`, `approved_pool`, `daily_manifest_pin`, `payload_budgets`,
`artist_family_exclusions`, `featured_albums`,
`editorial_albums`, `personal_seed`, `graph_rich_selection`, `coverage_gap_candidates`,
`album_art_cache_dir`, and the stage-scoped `round_seed_spec`, `full_corpus_root`,
`private_seed`, `editorial_seed` (Campaign Atlas SS).

The four stage-scoped inputs must still be stated, but are enforced (non-null, existing) only
when a selected stage needs them: `round_seed_spec` and `full_corpus_root` for `theme-supply`,
`full_corpus_root`, `private_seed` and `editorial_seed` (plus `approved_pool`) for
`onehop-rewiden`. Those two stages are **opt-in**: the default `round plan|run` covers the
publish sequence only, and they run when named with `--only-stage`, `--from-stage` or
`--to-stage`. See `docs/EXPANSION_PIPELINE.md`.

Some are required by a builder (the first six, and `album_art_cache_dir` for a real art run):
a `null` there is a valid spec but fails `round plan`, naming the builder. `approved_pool` is
required in this version because `validate-public-artifacts` has no pool-less mode.
`daily_manifest_pin` and `payload_budgets` are required for the same reason: the verify stage
passes them to `validate-public-artifacts` together with the round's own output directory, so a
round is checked against the committed pin over already-played daily dates (a round must never
change one) and the committed payload budgets, not against whatever a default path resolves to.

## Parameters never come from code defaults

`round plan` resolves each parameter as explicit, inherited or default (the same
`build_parameters` helpers the builders use). A parameter that would resolve to a code default
is a precondition failure: state it in the spec. (Round 1 shipped a halved two-hop pool
through exactly this.)

## Output layout

The runner writes the published layout under `output_dir` and, in `work_dir`, `stage-results.json`
(each builder's parameters and their sources) and `report.md`. The report contains no timing or
memory figures (ADR 0018).
