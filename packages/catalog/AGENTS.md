# Agent guidance — packages/catalog

The first implemented package: the Discogs release-ingestion vertical slice. See `README.md`
here for the full command walkthrough and output tables; this is the quick orientation.

- **Commands** run from the repo root via `make` / `uv` (Python 3.12, `uv sync --extra dev`).
  CLI surface: `manifest`, `download`, `parse-releases`, `validate` (see README). Tests live
  in `tests/`; run `uv run pytest` (or `make test`). `make check` mirrors CI.
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
