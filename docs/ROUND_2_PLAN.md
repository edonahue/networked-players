# Round 2 execution plan (Campaign Atlas)

Status: approved by the owner on 2026-11-18 ("plan then proceed to round 2 when ready").
Target: 217 → about 277 published records. Themes and seeds:
`data/rounds/round-2-seed-spec-v1.json` (owner-confirmed). Lanes: 36 theme / 15 graph value /
9 coverage repair.

Owner gates are marked **[owner]**. Everything else proceeds without asking, inside the fleet
runbook. Timings and memory figures stay in `local/benchmarks/` (ADR 0018).

| Step | Work | Gate to move on |
| --- | --- | --- |
| R2-0 | Supply fixes (#299): bounded format classification; per-artist cap and reserved overlap share in the seed spec; live-album eligibility check; real supply re-run | independent review clean; every theme meets its quota from a mixed pool |
| R2-1 | Fleet rollout of #280/#289 per `docs/OPERATOR_SETUP.md` checklist steps 1–6 | `platform-status` all `match`; a docs-only commit leaves the fleet eligible; ADR 0073 → Accepted |
| R2-2 | Bounded scoring corpus: the one-hop corpus plus the credits of every candidate release, extracted from the full corpus (the full corpus is 12 GB and cannot be replicated to any worker) | parity test on fixtures: scoring against the extract equals scoring against the full corpus |
| R2-3 | Score candidates: single-node on the coordination host with memory caps; shard to the fleet (#289) only if single-node is measured too slow | scored file covers every eligible candidate |
| R2-4 | Graph-value and coverage-repair lanes (existing supply/scorers, `docs/EXPANSION_PIPELINE.md` steps 0–8) | each lane's pool ≥ its quota, or the shortfall is reported |
| R2-5 | Review packet (`build-review-packet --mode round`) | **[owner]** approves ~60 albums; pool PR merged |
| R2-6 | G1a: one evidence-release policy for graph, challenge and routes (lands only with this rebuild) | parity tests; graph and challenge cite the same release per hop |
| R2-7 | `onehop-rewiden` for the approved albums (workstation), replicate to workers | replica checksums match |
| R2-8 | `round plan` → freeze the live daily generation → `round run` → `round verify` (lineage, G1b hop check, continuity, daily manifest, budgets); album-art stage is operator-run | all checks green; 0 lost path endpoints; cutover date still in the future |
| R2-9 | Rollback drill on a throwaway branch (revert all but the daily manifest and generations) | drill succeeds |
| R2-10 | One round PR; preview deploy | **[owner]** play-test and go/no-go; merge; post-deploy smoke |
| R2-11 | Re-run the album-projection study (ADR 0072 addendum); marginal-returns record | coverage still passes, or Collections revert to seed-driven |

Known risks: the coordination host has 8 GB and runs in swap (keep heavy steps bounded);
`zimaworker1` is an 8 GB ZimaBoard 832, not a 1664 (verified 2026-11-18), so there is no
16 GB node; the 12 GB full corpus fits nowhere but the coordination host.
