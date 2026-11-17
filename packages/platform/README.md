# Platform

The capability and run-contract layer for bounded home-cluster jobs. It is deliberately
independent of Discogs, DuckDB, Ansible, and any hostname. Domain packages register
workloads later; this package owns worker advertisements, selection, run provenance,
and atomic output staging.

The standing runtime reads private configuration from environment variables:
`JOBS_BROKER_URL`, `PLATFORM_WORKER_ID`, `PLATFORM_TAGS`,
`PLATFORM_MAX_JOB_MEMORY_MB`, `PLATFORM_RUNTIME_COMMIT`, and a JSON dataset list.
Ansible writes these to a mode-0600 file; they are not committed or printed by the
deployment playbook.

## Runtime digests (ADR 0073)

Worker eligibility is a per-workload runtime digest (`digest.py`), not the git commit, which
stays recorded as provenance. The digest covers every `.py` and packaged `.json` file of each
`networked_players_*` package in the workload's import closure, plus `uv.lock`. Observed
closures (asserted in `tests/test_runtime_digest.py`):

| Workload | Packages hashed |
| --- | --- |
| `platform.self-test`, `artifact.validate`, `research.corpus-check` | platform, contracts |
| `cohort.score` | platform, contracts, catalog, graph-core |
| `research.graph-metrics` | platform, contracts, graph-core, research |

Workers set `PLATFORM_RELEASE_JSON` (written by `deploy-platform-runtime.yml`) so the runtime
can read the release's `uv.lock` hash; without it a worker advertises no digests and is
refused with an explicit reason. `networked-players-platform runtime-digests` prints a
checkout's digests; `jobs list|status|cancel|logs` is the operator job view.
