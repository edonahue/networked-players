# Repository integrity records

Small committed files that guard published artifacts. They live here, not under
`apps/web/public/`, because they are repository integrity records that no
browser needs; the served site stays untouched. Every value is derived from
already-public artifacts (hashes and byte counts), so nothing here is private.

- `daily-manifest-pin-v1.json` -- pin over already-played daily dates (ADR 0041,
  ADR 0066). Validated by `validate-public-artifacts`; advanced with
  `advance-daily-manifest-pin` as part of the schedule-extension routine
  (`docs/OPERATOR_SETUP.md`, "Daily-schedule extension").
- `payload-budgets-v1.json` -- payload budgets for the public data tree
  (`graph.v4.json` gzip hard budget 2.5 MB, warning 2.0 MB; raw total ceiling
  60 MB, about 1.9x the 31.0 MB at the time it was set, so a deliberate round
  never trips it but an accidental multi-fold blow-up does). Changing a budget
  is a reviewed diff to this file. Sizes use deterministic gzip
  (`compresslevel=9, mtime=0`).
