# Agent guidance — packages/catalog

The first implemented package: the Discogs release-ingestion vertical slice. See `README.md`
here for the full command walkthrough and output tables; this is the quick orientation.

- **Commands** run from the repo root via `make` / `uv` (Python 3.12, `uv sync --extra dev`).
  The original four ingestion commands (`manifest`, `download`, `parse-releases`, `validate`)
  are just the start: the real `networked-players-catalog` CLI has grown to 73 subcommands
  (catalog/art/rounds/routes/daily-manifest build+validate pairs, the cohort pipeline,
  contributor index, pathfinding graph, evidence registry, and more) — see README.md here for
  the ingestion walkthrough. `docs/OPERATOR_SETUP.md` covers selected operator workflows, not
  every subcommand (verified: 35 of the 73 aren't mentioned there) — for the actual complete,
  always-current list, run `networked-players-catalog --help` (or `<subcommand> --help`), not
  a curated doc. Tests live in `tests/`; run `uv run pytest` (or `make test`). `make check`
  mirrors CI's Python-workflow gate (see the root `CONTRIBUTING.md` for the separate `apps/web`
  gate).
- **Schema source of truth:** the PyArrow schemas in
  `src/networked_players_catalog/discogs/parquet.py` (`SCHEMA_VERSION`). The contract doc
  `data/contracts/discogs-release-v2.md` tracks them — if they disagree, the code wins.
- **Evidence rules (do not break):** keep PAN `artist_id` separate from ANV display text;
  retain non-linked names as evidence but never as playable identities; preserve original
  role text, source URL, snapshot date, and parser/schema versions. Stream gzip XML and clear
  parsed elements — never require expanded XML on disk.
- **Resource posture:** a full raw dump is workstation/coordination-host work, never a Pi job;
  Pi workers consume only bounded, checksummed partitions.
- Keep fixtures synthetic and privacy-safe; never add real dumps or collection exports.
