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
