# Tests

There is no cross-project suite in this directory. Tests live next to the code they cover:

- `packages/*/tests/` — pytest suites for each Python package (run by `make check`, in
  parallel via `pytest -n auto`), using synthetic fixtures only;
- `apps/web/tests/` — Playwright smoke, accessibility, and pure-node specs for the site
  (`npm run test:smoke` in `apps/web/`);
- `validate-public-artifacts` and `validate-album-catalog-audit` — contract validation of
  the real committed artifacts, also part of `make check`.
