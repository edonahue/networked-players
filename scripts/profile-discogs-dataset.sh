#!/usr/bin/env bash
#
# Profile a completed, real Discogs Parquet dataset with the standalone DuckDB
# CLI (scripts/install-duckdb-cli.sh) -- dimensions, per-column null/format
# rates, distribution/enum breakdowns, and encoding/outlier spot checks.
# Read-only: never writes to the dataset. Reusable across snapshots, so a
# future monthly refresh gets the same profiling pass for free.
#
# Every query runs with DuckDB's own `.timer on`, so its printed "Run Time"
# after each result is a real per-query measurement, not a bash-level
# approximation -- see docs/discogs-data/raw-dump-schema.md's "Query
# performance and DB setup" section for how to read these numbers.
#
# Config (env vars, or sourced from git-ignored local/ingest.env, same
# pattern as scripts/run-ingest.sh):
#   SNAPSHOT       Required. YYYYMMDD, matching an already-completed
#                  `parse-releases` run (e.g. 20260601).
#   PROCESSED_DIR  Optional. Default: local/processed/discogs
#
# Usage:  SNAPSHOT=20260601 ./scripts/profile-discogs-dataset.sh
# Usage:  SNAPSHOT=20260601 ./scripts/profile-discogs-dataset.sh > local/monitoring/profile-20260601.txt
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f local/ingest.env ]]; then
  # shellcheck disable=SC1091
  source local/ingest.env
fi

: "${SNAPSHOT:?Set SNAPSHOT=YYYYMMDD, e.g. SNAPSHOT=20260601}"
PROCESSED_DIR="${PROCESSED_DIR:-local/processed/discogs}"
DATASET_ROOT="${PROCESSED_DIR}/snapshot=${SNAPSHOT}"

if ! command -v duckdb >/dev/null 2>&1; then
  echo "ABORT: duckdb CLI not found on PATH. Install it with:" >&2
  echo "    ./scripts/install-duckdb-cli.sh" >&2
  exit 1
fi

if [[ ! -d "${DATASET_ROOT}/table=releases" ]]; then
  echo "ABORT: no dataset at ${DATASET_ROOT} -- run scripts/run-ingest.sh first." >&2
  exit 1
fi

RELEASES_GLOB="${DATASET_ROOT}/table=releases/*.parquet"
TRACKS_GLOB="${DATASET_ROOT}/table=tracks/*.parquet"
CREDITS_GLOB="${DATASET_ROOT}/table=credits/*.parquet"

echo "==> Profiling snapshot=${SNAPSHOT} at ${DATASET_ROOT}"
echo "==> DuckDB: $(duckdb --version)"
echo "==> Host: $(uname -srm), $(nproc) CPU(s)"
echo

duckdb <<SQL
.timer on
.mode box

CREATE VIEW releases AS SELECT * FROM '${RELEASES_GLOB}';
CREATE VIEW tracks   AS SELECT * FROM '${TRACKS_GLOB}';
CREATE VIEW credits  AS SELECT * FROM '${CREDITS_GLOB}';

.print '--- Section 1: Dimensions & referential shape ---'

SELECT
  (SELECT count(*) FROM releases) AS release_rows,
  (SELECT count(*) FROM tracks)   AS track_rows,
  (SELECT count(*) FROM credits)  AS credit_rows;

SELECT
  round((SELECT count(*) FROM tracks)::DOUBLE  / (SELECT count(*) FROM releases), 2) AS avg_tracks_per_release,
  round((SELECT count(*) FROM credits)::DOUBLE / (SELECT count(*) FROM releases), 2) AS avg_credits_per_release;

SELECT count(*) AS releases_with_zero_tracks
FROM releases r ANTI JOIN tracks t USING (release_id);

SELECT count(*) AS releases_with_zero_credits
FROM releases r ANTI JOIN credits c USING (release_id);

.print '--- Section 2: Releases column profiling ---'

SELECT
  sum((status IS NULL)::INT)             AS status_null,
  sum((title IS NULL)::INT)              AS title_null,
  sum((country IS NULL)::INT)            AS country_null,
  sum((released IS NULL)::INT)           AS released_null,
  sum((master_id IS NULL)::INT)          AS master_id_null,
  sum((master_is_main_release IS NULL)::INT) AS master_is_main_release_null,
  sum((data_quality IS NULL)::INT)       AS data_quality_null
FROM releases;

SELECT country, count(*) n FROM releases GROUP BY 1 ORDER BY 2 DESC LIMIT 10;

SELECT data_quality, count(*) n FROM releases GROUP BY 1 ORDER BY 2 DESC;

SELECT
  CASE
    WHEN released IS NULL OR released = '' THEN 'empty/null'
    WHEN regexp_matches(released, '^[0-9]{4}\$') THEN 'year-only'
    WHEN regexp_matches(released, '^[0-9]{4}-[0-9]{2}-[0-9]{2}\$')
         AND released NOT LIKE '%-00' AND released NOT LIKE '%-00-%' THEN 'full-date'
    WHEN regexp_matches(released, '^[0-9]{4}-[0-9]{2}-00\$') THEN 'partial-day'
    WHEN regexp_matches(released, '^[0-9]{4}-00-00\$') THEN 'partial-month'
    ELSE 'other/malformed'
  END AS shape, count(*) n
FROM releases GROUP BY 1 ORDER BY 2 DESC;

SELECT count(*) AS mojibake_title_candidates
FROM releases WHERE title LIKE '%Ã%' OR title LIKE '%â€%' OR title LIKE '%�%';

SELECT release_id, master_id, master_is_main_release
FROM releases WHERE master_id IS NULL AND master_is_main_release = true;

.print '--- Section 3: Tracks column profiling ---'

SELECT
  sum((title IS NULL)::INT)    AS title_null,
  sum((position IS NULL)::INT) AS position_null,
  sum((duration IS NULL OR duration = '')::INT) AS duration_empty,
  sum((regexp_matches(duration, '^[0-9]+:[0-9]{2}\$'))::INT) AS duration_mmss,
  sum((parent_track_index IS NOT NULL AND parent_track_index >= 0)::INT) AS nested_sub_tracks,
  count(*) AS total
FROM tracks;

SELECT duration, count(*) n
FROM tracks
WHERE NOT (duration IS NULL OR duration = '' OR regexp_matches(duration, '^[0-9]+:[0-9]{2}\$'))
GROUP BY 1 ORDER BY 2 DESC LIMIT 15;

SELECT position, count(*) n FROM tracks GROUP BY 1 ORDER BY 2 DESC LIMIT 15;

.print '--- Section 4: Credits column profiling ---'

SELECT credit_scope, count(*) n FROM credits GROUP BY 1 ORDER BY 2 DESC;

SELECT is_linked, playable_identity, count(*) n
FROM credits GROUP BY 1, 2 ORDER BY 3 DESC;

SELECT
  sum((anv IS NOT NULL)::INT)                  AS anv_present,
  sum((join_text IS NOT NULL)::INT)            AS join_text_present,
  sum((credited_tracks_text IS NOT NULL)::INT) AS credited_tracks_text_present,
  count(*) AS total
FROM credits;

SELECT join_text, count(*) n FROM credits WHERE join_text IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10;

SELECT role_text, count(*) n FROM credits WHERE role_text IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 15;

SELECT count(DISTINCT role_text) AS distinct_role_text FROM credits;

SELECT
  CASE WHEN length(role_text) <= 20 THEN '<=20'
       WHEN length(role_text) <= 50 THEN '21-50'
       WHEN length(role_text) <= 200 THEN '51-200'
       ELSE '200+' END AS bucket,
  count(*) n, max(length(role_text)) maxlen
FROM credits WHERE role_text IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;

SELECT artist_id, name, count(*) n
FROM credits WHERE is_linked GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 15;

.print '--- Section 5: Outlier / encoding spot checks ---'

SELECT title FROM releases
WHERE title LIKE '%Ã%' OR title LIKE '%â€%' OR title LIKE '%�%' LIMIT 10;

SELECT max(length(title)) AS max_title_len FROM releases;
SELECT max(length(name)) AS max_credit_name_len FROM credits;
SQL

echo
echo "==> Done. Each result above was preceded by DuckDB's own \"Run Time\" line"
echo "    (query compilation + execution, printed by .timer on)."
