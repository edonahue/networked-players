# Architecture decisions

Decision records explain consequential choices and their revisit triggers. They describe current direction without pretending implementation is complete.

File naming:

```text
NNNN-short-decision-title.md
```

A decision should include status, date, context, decision, consequences, validation, and revisit trigger.

## Index

Status is the first clause of each record's own **Status** line; open the record for
amendments and addenda. Regenerate this table when adding a record.

| ADR | Title | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-public-by-default.md) | Develop in public by default | Accepted | 2026-06-28 |
| [0002](0002-static-first-public-experience.md) | Make the public experience static first | Accepted | 2026-06-28 |
| [0003](0003-monorepo.md) | Begin as one monorepo | Accepted | 2026-06-28 |
| [0004](0004-canonical-product-domain.md) | Use a canonical game-hosting domain | Accepted | 2026-06-29 |
| [0005](0005-discogs-hybrid-acquisition.md) | Use a hybrid Discogs acquisition strategy | Accepted | 2026-06-29 |
| [0006](0006-stream-discogs-gzip-to-parquet.md) | Stream release gzip into bounded Parquet partitions | Accepted | 2026-06-29 |
| [0007](0007-zimaboard-swarm-manager.md) | Bootstrap the ZimaBoard 832 as the initial Docker Swarm manager | Accepted | 2026-06-30 |
| [0008](0008-portainer-swarm-visibility.md) | Add Portainer CE for Swarm visibility, deferring metrics tooling | Accepted | 2026-07-01 |
| [0009](0009-portainer-tailscale-access.md) | Access Portainer via Tailscale instead of an SSH tunnel | Accepted | 2026-07-01 |
| [0010](0010-coordination-stack-ahead-of-nvme.md) | Bring up the coordination Postgres/Redis stack ahead of the NVMe | Accepted | 2026-07-01 |
| [0011](0011-private-seed-contract.md) | Private seed contract -- release-IDs-only JSON, stored under data/private/ | Accepted | 2026-07-01 |
| [0012](0012-real-discogs-api-demo-challenge.md) | Real Discogs-API demo challenge -- images, curated subset, ahead of Milestone 8 | Accepted | 2026-07-01 |
| [0013](0013-nvme-storage-layout.md) | NVMe storage layout and coordination-stack relocation | Accepted | 2026-07-01 |
| [0014](0014-coordination-host-hardening.md) | Coordination host hardening for long-running background jobs | Accepted | 2026-07-01 |
| [0015](0015-fleet-onboarding.md) | Fleet onboarding tooling for Pi workers and a second ZimaBoard | Accepted | 2026-07-01 |
| [0016](0016-state-backup-and-recovery.md) | State backup and recovery for the coordination host | Accepted | 2026-07-02 |
| [0017](0017-guarded-swarm-worker-join-automation.md) | Guarded, repeatable Swarm worker join automation | Accepted | 2026-07-02 |
| [0018](0018-benchmark-results-local-only.md) | Benchmark results are local-only; the method stays public | Accepted | 2026-07-03 |
| [0019](0019-cluster-benchmark-rq-job-broker.md) | Cluster-vs-single-node RQ benchmark, and its LAN-reachable job broker | Amended by ADR 0034 | 2026-07-03 |
| [0020](0020-dask-jupyter-interactive-cluster-compute.md) | Adopt Dask + Jupyter for interactive cluster compute | Amended by ADR 0034 | 2026-07-03 |
| [0021](0021-canonical-benchmarks-and-dask-rq-isolation.md) | Canonical Pi benchmarks, and automated Dask/RQ contention isolation | Accepted | 2026-07-03 |
| [0022](0022-second-zimaboard-joins-as-x86-swarm-worker.md) | The second ZimaBoard joins the Swarm as a dedicated x86_64 worker | Accepted | 2026-07-03 |
| [0023](0023-x86-worker-joins-rq-dask-fleet-work.md) | The x86_64 Swarm worker joins RQ/Dask fleet work, at a higher-capability tier | Amended by ADR 0034 | 2026-07-04 |
| [0024](0024-http-readonly-catalog-data-access.md) | Read-only HTTP access to catalog datasets for remote workers | Accepted | 2026-07-04 |
| [0025](0025-worker-local-dataset-cache.md) | Worker-local, disposable, verified dataset caches | Accepted | 2026-07-04 |
| [0026](0026-exclude-placeholder-artists-from-one-hop-frontier.md) | Exclude Discogs placeholder identities from the one-hop frontier | Accepted | 2026-07-04 |
| [0027](0027-exclude-non-performer-roles-from-one-hop-frontier.md) | Exclude pure non-performer role credits from the one-hop frontier | Accepted | 2026-07-04 |
| [0028](0028-curated-cohort-source-ingestion.md) | Curated cohort source ingestion (saved HTML, never live-fetched) | Accepted | 2026-07-05 |
| [0029](0029-connectivity-scorer-flags-dont-fix-traversal-gap.md) | Connectivity scorer flags the CreditGraph/onehop.py exclusion gap, doesn't fix it at the source | Superseded by ADR 0035 (2026-07-10) | 2026-07-05 |
| [0030](0030-cohort-scoped-connectivity-substrate.md) | Cohort connectivity scoring uses a per-cohort-artist BFS with a shared neighbor cache, not per-pair `CreditGraph.find_path` calls | Accepted | 2026-07-05 |
| [0031](0031-human-reviewed-cohort-promotion.md) | Human-reviewed cohort promotion uses a selection file, not CLI-flag pair selection | Accepted | 2026-07-05 |
| [0032](0032-cohort-seed-bfs-fleet-dispatch.md) | Cohort connectivity's fleet-distribution dispatch unit is a chunk of unique seed artists, mirroring `verify_challenge_job.py` | Superseded by ADR 0034 | 2026-07-09 |
| [0033](0033-memory-bounded-cohort-scoring.md) | Cohort connectivity scoring is memory-bounded and bidirectional — reach rows in DuckDB, not parent maps in Python | Accepted | 2026-07-09 |
| [0034](0034-capability-routed-home-compute-platform.md) | Capability-routed home compute platform | Accepted | 2026-07-10 |
| [0035](0035-track-scoped-credit-edges.md) | An edge means "contributed to the same recording", not "appears on the same release" | Accepted | 2026-07-10 |
| [0036](0036-interim-release-title-curation-filter.md) | Interim title filter for compilation-like evidence releases | Accepted, interim | 2026-07-11 |
| [0037](0037-web-game-universe-and-round-engine.md) | Web game universe and round engine | Accepted | 2026-07-18 |
| [0038](0038-hybrid-album-catalog-assembly.md) | Hybrid album catalog assembly for the real-data launch | Accepted | 2026-07-19 |
| [0039](0039-performer-allowlist-layered-for-game-rounds.md) | A fail-closed performer allowlist, layered only for game rounds | Accepted | 2026-07-19 |
| [0040](0040-parse-artist-relations-for-family-exclusion.md) | Parse real Discogs group/member relations instead of hand-curating an exclusion list | Accepted | 2026-07-19 |
| [0041](0041-frozen-append-only-daily-manifest.md) | A frozen, append-only date-to-round manifest (original design) | Accepted | 2026-07-19 |
| [0042](0042-real-connection-guesser-pool.md) | A real, Python-generated Connection Guesser pool replaces the synthetic-first one | Accepted | 2026-07-20 |
| [0043](0043-connection-guesser-corrective-slice.md) | Corrective slice for the real Connection Guesser pool (slices 4.5, 4.6) | Accepted | 2026-07-21 |
| [0044](0044-phase1-launch-daily-state-and-art-decoupling.md) | Phase 1 launch — pre-launch daily state and presentation-art decoupling | Accepted | 2026-07-21 |
| [0045](0045-album-art-registry-and-launch-cutover.md) | Album-art registry and the art-first daily launch cutover | Accepted | 2026-07-22 |
| [0046](0046-record-routes-productionization.md) | Record Routes productionization | Accepted | 2026-07-22 |
| [0047](0047-role-taxonomy-as-a-third-orthogonal-classification-layer.md) | A role taxonomy as a third, orthogonal classification layer | Accepted | 2026-08-03 |
| [0048](0048-contributor-index-and-pages.md) | Contributor index and pages | Accepted (one question answered later) | 2026-08-03 |
| [0049](0049-exploration-tier-policy-and-versioning.md) | Exploration-tier policy and versioning | Accepted | 2026-08-03 |
| [0050](0050-browser-pathfinding-architecture-selection.md) | Browser-local, bounded-scope pathfinding for Connect Two Records | Accepted | 2026-08-03 |
| [0051](0051-connect-two-records.md) | Connect Two Records — the first search UI | Accepted | 2026-08-03 |
| [0052](0052-network-explorer-svg-bounded-radius.md) | Network Explorer — SVG, bounded radius, no force-directed layout | Accepted | 2026-08-03 |
| [0053](0053-role-aware-game-mode-selection.md) | Role-aware game mode selection — Behind the Glass | Accepted | 2026-08-03 |
| [0054](0054-research-lane-and-promotion-boundary.md) | A research lane, strictly separate from the public/publication lane | Accepted | 2026-08-04 |
| [0055](0055-research-graph-library-selection.md) | igraph for offline research graph analytics | Accepted | 2026-08-04 |
| [0056](0056-unify-pi-fleet-checks-onto-capability-platform.md) | unify Pi-fleet artifact checks onto the ADR 0034 capability platform | Accepted | 2026-08-04 |
| [0057](0057-zimaworker1-storage-and-capacity-policy.md) | zimaworker1 gets an explicit storage/capacity policy after a real disk-full incident | Accepted | 2026-08-04 |
| [0058](0058-album-credit-membership-and-evidence-registry.md) | Album-credit membership, evidence-release registry, and record-to-record pathfinding | Accepted | 2026-08-07 |
| [0059](0059-recommended-route-selection.md) | Recommended documented route selection | Accepted | 2026-08-14 |
| [0060](0060-interesting-next-step-signal.md) | `interesting_next_step` — a role-disjoint, anti-hub contributor signal | Accepted | 2026-08-16 |
| [0061](0061-scope-tier-corpus-design-deferred.md) | corpus scope-tier design stays deferred — no contract change yet | Accepted | 2026-08-16 |
| [0062](0062-pi-fleet-verify-challenge-migration-deferred.md) | `enqueue_verify_challenge.py`'s ADR-0034 migration stays deferred | Accepted | 2026-08-17 |
| [0063](0063-bridge-contributors-promotion-rejected.md) | `bridge_analysis` (betweenness) promotion — measured and rejected | Accepted | 2026-08-17 |
| [0064](0064-traversal-role-policy-for-album-anchors-and-film-credits.md) | Traversal role policy — album anchors and film/video credits | Accepted | 2026-08-27 |
| [0065](0065-phase7-bucket-a-personal-lane-allocation.md) | Phase 7 Bucket A allocation — 13 personal, not 16 | Accepted | 2026-08-27 |
| [0066](0066-phase7-daily-manifest-schedule-rewrite-exception.md) | A bounded, human-authored exception to the never-rewrite daily-manifest rule | Accepted | 2026-08-27 |
| [0067](0067-album-shelf-shows-the-full-catalog.md) | The album shelf shows the full catalog, not just challenge.v2-connected albums | Accepted | 2026-08-29 |
| [0068](0068-performer-only-public-graph.md) | Public connections mean documented musical performance | Accepted | 2026-09-01 |
| [0069](0069-public-universe-model-and-expansion-policy.md) | Public universe model and expansion policy (graph-expansion Phase 0) | Accepted (domain model and eligibility foundation) | — |
| [0070](0070-community-detection-and-explore-scaling-measurement.md) | Community detection is measured and denied; Explore scaling gets a real recenter budget | Accepted (superseded in part) | 2026-09-03 |
| [0071](0071-pathfinding-graph-v4-role-dictionary.md) | Pathfinding graph v4 — role-text dictionary encoding | Accepted and fully rolled out | — |
