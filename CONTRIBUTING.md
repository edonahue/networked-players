# Contributing

Networked Players is currently a personal learning and portfolio project. Thoughtful issues, corrections, design discussion, and small pull requests are welcome.

## Before contributing

1. Read the project principles in `README.md`.
2. Read `docs/PUBLIC_PRIVATE_BOUNDARY.md` before adding data or infrastructure material.
3. Search existing issues and decisions.
4. Keep the proposed change proportional to the project's current maturity.

## Set up your environment

1. Install the [prerequisites](README.md#develop): `uv`, Python 3.12+, and the `libxml2`/`libxslt` dev headers.
2. `make setup` (installs dependencies with dev extras).
3. `make check` before pushing — it runs lint, format check, type check, tests, and the two committed-artifact validation gates (`validate-public-artifacts`, `validate-album-catalog-audit`), mirroring CI exactly.

Optionally, `uvx pre-commit install` enables the local hooks in `.pre-commit-config.yaml`.

## Pull requests

A useful pull request should explain:

- the user or learning outcome;
- what changed and why;
- whether it changes a settled decision;
- what data, security, or rights considerations apply;
- how the change was checked.

Do not submit generated frameworks, speculative abstractions, or large dependency sets without a concrete vertical-slice need.

## Data and examples

Only commit data that is synthetic, intentionally public, or clearly redistributable. Do not commit personal collection exports, account-linked fields, private API responses, or database snapshots.

## Licensing

Code is licensed under the [MIT License](LICENSE). By submitting a
contribution, you agree it is licensed under the same terms. This does not
cover Discogs-derived catalog data or generated artifacts — see
[docs/DATA_AND_RIGHTS.md](docs/DATA_AND_RIGHTS.md).
