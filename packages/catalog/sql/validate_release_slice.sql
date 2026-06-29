-- Human-readable equivalents of the invariants enforced by validation.py.
SELECT count(*) AS duplicate_release_ids
FROM (
  SELECT release_id
  FROM releases
  GROUP BY release_id
  HAVING count(*) > 1
);

SELECT count(*) AS orphan_credits
FROM credits c
ANTI JOIN releases r USING (release_id);

SELECT count(*) AS invalid_linked_artist_ids
FROM credits
WHERE is_linked AND (artist_id IS NULL OR artist_id <= 0);
