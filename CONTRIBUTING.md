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
3. `make check` before pushing — it runs lint, format check, type check, and tests, mirroring CI.

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

No open-source license has been selected. Contributions should not be submitted with the expectation that the repository is already licensed for general reuse or redistribution.
