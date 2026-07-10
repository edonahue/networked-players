# Contracts

Dependency-free validators shared by catalog tooling, the web publication pipeline,
and constrained workers. Contract code accepts plain JSON-shaped dictionaries and
returns every structural, privacy, and wording failure it finds.

This package deliberately has no cluster, DuckDB, parsing, or web dependency. A Pi
worker can install it without inheriting the full catalog toolchain.
