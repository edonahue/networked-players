# Platform

The capability and run-contract layer for bounded home-cluster jobs. It is deliberately
independent of Discogs, DuckDB, Ansible, and any hostname. Domain packages register
workloads later; this package owns worker advertisements, selection, run provenance,
and atomic output staging.
