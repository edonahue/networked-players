# Round seed specs

Committed, public declarations of what an expansion round is seeded from
(contract: [`data/contracts/round-seed-spec-v1.md`](../contracts/round-seed-spec-v1.md)).
Naming a theme approves no album ([ADR 0072](../../docs/decisions/0072-campaign-atlas-lineage-approved-pool-collections.md) section 7).

## TODO (owner/operator): the real Round 2 spec

`round-2-seed-spec-v1.json` is deliberately **not** in the repository yet. Its seed ids must be
real, verified Discogs ids and none have been verified here. To create it, copy
`data/fixtures/round-seed-spec/synthetic-round-seed-spec-v1.json` and fill in:

- `round`: 2; `target_count`: 60 (217 to about 277 albums); `lane_shares_percent`:
  `{"theme": 60, "graph_value": 25, "coverage_repair": 15}`.
- Three themes chosen by the owner on 2026-11-15: the acid-jazz / Jamiroquai orbit, desert rock,
  and jazz fusion. For each: `seed_artist_ids` and/or `seed_master_ids` looked up on discogs.com
  or in the full parsed corpus, optional `styles`/`genres` tags (exact Discogs spellings),
  `year_min`/`year_max`, `min_shared_performers` (2 is the hub-trap-safe choice) and
  `candidate_cap`.
- Validate with `networked-players-catalog validate-round-seed-spec --spec <file>`.

Never put collection membership, scores or reviewer identity in the file.
